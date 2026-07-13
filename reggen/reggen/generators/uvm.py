"""UVM register block generator (M4).

Consumes the IR and emits a `uvm_reg_block` (with a `uvm_reg` per register and a
`uvm_reg_field` per field) wrapped in a package. The verification env gets a RAL
model with front-door / back-door access and a built-in predictor/scoreboard.

Two decisions that are easy to get wrong live here in Python (so they are
unit-testable) rather than in the template:

  * uvm_reg_field::configure() argument order:
        configure(parent, size, lsb_pos, access, volatile, reset,
                  has_reset, is_rand, individually_accessible)
  * mapping reggen's 8 access policies onto UVM's built-in field policies, and
    deriving `volatile` (HW may change the field without software) and `is_rand`
    (only software-writable fields are worth randomizing).
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ..ir import Field, Register, RegisterMap, build_ir
from ..loader import load_spec

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_TEMPLATE = "uvm_reg_block.sv.j2"

# reggen access policy -> UVM built-in field access policy string.
UVM_ACCESS = {
    "RW": "RW",
    "RO": "RO",
    "WO": "WO",
    "W1C": "W1C",
    "W1S": "W1S",
    "RW1C": "W1C",
    "RW1S": "W1S",
    "RC": "RC",
}


class FieldUView:
    """One uvm_reg_field's configure() arguments, precomputed."""

    def __init__(self, f: Field):
        self.name = f.name
        self.size = f.width
        self.lsb = f.lsb
        self.access = UVM_ACCESS[f.access.name]
        # HW can change the field behind software's back -> mark volatile.
        self.volatile = 1 if f.access.hw_writable else 0
        self.reset = f.reset
        self.has_reset = 1
        # Only fields software can write are meaningful to randomize.
        self.is_rand = 1 if f.access.sw_writable else 0
        self.individually_accessible = 0


class RegUView:
    def __init__(self, reg: Register):
        self.name = reg.name
        self.class_name = f"{reg.name}_reg"
        self.width = reg.width
        self.offset = reg.offset
        self.fields = [FieldUView(f) for f in reg.fields]
        self.rights = self._rights(reg)

    @staticmethod
    def _rights(reg: Register) -> str:
        """Register-level access rights for uvm_reg_map::add_reg()."""
        has_read = any(f.access.readable for f in reg.fields)
        has_write = any(f.access.sw_writable for f in reg.fields)
        if has_write and not has_read:
            return "WO"
        if has_read and not has_write:
            return "RO"
        return "RW"


def _make_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def generate_uvm(rmap: RegisterMap, pkg_name: str | None = None) -> str:
    """Render the UVM register-block package for a RegisterMap."""
    block = rmap.block
    pkg = pkg_name or f"{block.name}_reg_pkg"
    registers = [RegUView(r) for r in rmap]

    env = _make_env()
    template = env.get_template(_TEMPLATE)
    return template.render(
        pkg=pkg,
        block=block,
        block_class=f"{block.name}_reg_block",
        data_bytes=block.data_width // 8,
        base_address=block.base_address,
        registers=registers,
    )


def generate_uvm_from_spec(spec: dict, pkg_name: str | None = None) -> str:
    return generate_uvm(build_ir(spec), pkg_name)


def generate_uvm_from_file(path: str | Path, pkg_name: str | None = None) -> str:
    return generate_uvm(build_ir(load_spec(path)), pkg_name)
