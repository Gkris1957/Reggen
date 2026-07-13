"""SystemVerilog AXI-Lite CSR slave generator (M3).

Consumes the IR (RegisterMap) and emits a synthesizable AXI4-Lite register
slave. All bit-math and per-field logic decisions are computed here, in Python,
where they are unit-testable; the Jinja template only lays the pieces out.

Hardware model per access policy
--------------------------------
  RW / WO   : CSR owns storage; exposes `<f>_o` (current value to the design).
  RO        : no storage; design drives `<f>_i`, read mux returns it.
  W1C/RW1C  : storage; design pulses `<f>_set_i` (HW set wins), SW writes 1 to
              clear; exposes `<f>_o`.
  W1S/RW1S  : storage; design pulses `<f>_clr_i` (HW clear wins), SW writes 1 to
              set; exposes `<f>_o`.
  RC        : storage; design pulses `<f>_set_i`, a SW read clears it; `<f>_o`.

The bus handshake is fully registered (no combinational VALID/READY path) and
writes are byte-strobed via an expanded WSTRB mask, so partial-word writes only
touch the addressed bytes.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ..ir import Field, Register, RegisterMap, build_ir
from ..loader import load_spec

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_TEMPLATE = "axil_csr.sv.j2"


def _category(f: Field) -> str:
    """Collapse the 8 access policies onto the 5 logic shapes the template emits."""
    a = f.access
    if a.on_read == "clear":
        return "rc"
    if a.on_write == "clear":
        return "w1c"
    if a.on_write == "set":
        return "w1s"
    if not a.sw_writable and a.hw_writable:  # RO
        return "ro"
    return "rw"  # RW, WO


def _signal_base(reg: Register, f: Field) -> str:
    """Base name for a field's signals/ports; implicit fields drop the redundant
    <reg>_<reg> doubling."""
    return reg.name if f.implicit else f"{reg.name}_{f.name}"


class FieldView:
    """Everything the template needs about one field, precomputed."""

    def __init__(self, reg: Register, f: Field):
        self.reg = reg.name
        self.name = f.name
        self.msb = f.msb
        self.lsb = f.lsb
        self.width = f.width
        self.reset = f.reset
        self.access = f.access.name
        self.category = _category(f)
        self.readable = f.access.readable
        base = _signal_base(reg, f)
        self.q = f"{base}_q"          # storage register
        self.port_o = f"{base}_o"     # value exposed to the design
        self.port_i = f"{base}_i"     # RO status input
        self.port_set = f"{base}_set_i"
        self.port_clr = f"{base}_clr_i"

    # --- SV slice helpers (template just prints these) ---
    @property
    def has_storage(self) -> bool:
        return self.category in ("rw", "w1c", "w1s", "rc")

    @property
    def slice(self) -> str:
        return f"[{self.msb}:{self.lsb}]" if self.width > 1 else f"[{self.lsb}]"

    @property
    def vslice(self) -> str:
        """Vector declaration slice for a width-sized signal."""
        return f"[{self.width - 1}:0]" if self.width > 1 else ""

    @property
    def read_source(self) -> str | None:
        """RHS expression driving the read mux for this field, or None if it
        reads back as 0 (write-only / no read)."""
        if not self.readable:
            return None
        if self.category == "ro":
            return self.port_i
        return self.q

    def port_decls(self) -> list[dict]:
        """Design-facing port declarations this field contributes (0, 1, or 2)."""
        tag = f"{self.reg}.{self.name} ({self.access})"
        v = self.vslice
        if self.category in ("rw", "wo"):
            return [{"dir": "output reg ", "vslice": v, "name": self.port_o, "comment": tag}]
        if self.category == "ro":
            return [{"dir": "input  wire", "vslice": v, "name": self.port_i, "comment": tag}]
        if self.category in ("w1c", "rc"):
            return [
                {"dir": "input  wire", "vslice": v, "name": self.port_set, "comment": f"{tag} HW set"},
                {"dir": "output reg ", "vslice": v, "name": self.port_o, "comment": f"{tag} value"},
            ]
        if self.category == "w1s":
            return [
                {"dir": "input  wire", "vslice": v, "name": self.port_clr, "comment": f"{tag} HW clear"},
                {"dir": "output reg ", "vslice": v, "name": self.port_o, "comment": f"{tag} value"},
            ]
        return []


class RegisterView:
    def __init__(self, reg: Register):
        self.name = reg.name
        self.offset = reg.offset
        self.description = reg.description
        self.fields = [FieldView(reg, f) for f in reg.fields]
        self.reset_value = reg.reset_value


def _wstrb_concat(data_width: int) -> str:
    """Expand WSTRB[n] into a per-bit write-enable mask, MSB byte first."""
    nbytes = data_width // 8
    parts = [f"{{8{{s_axi_wstrb[{b}]}}}}" for b in range(nbytes - 1, -1, -1)]
    return "{" + ", ".join(parts) + "}"


def _make_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def generate_sv(rmap: RegisterMap, module_name: str | None = None) -> str:
    """Render the AXI-Lite CSR slave SystemVerilog for a RegisterMap."""
    block = rmap.block
    module = module_name or f"{block.name}_axil_csr"
    registers = [RegisterView(r) for r in rmap]

    ports = [pd for r in registers for f in r.fields for pd in f.port_decls()]

    env = _make_env()
    template = env.get_template(_TEMPLATE)
    return template.render(
        module=module,
        block=block,
        data_width=block.data_width,
        addr_width=block.addr_width,
        registers=registers,
        ports=ports,
        wstrb_concat=_wstrb_concat(block.data_width),
    )


def generate_sv_from_spec(spec: dict, module_name: str | None = None) -> str:
    return generate_sv(build_ir(spec), module_name)


def generate_sv_from_file(path: str | Path, module_name: str | None = None) -> str:
    return generate_sv(build_ir(load_spec(path)), module_name)
