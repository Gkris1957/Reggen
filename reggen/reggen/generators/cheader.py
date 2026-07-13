"""C header generator (M5).

Emits a portable register-access header from the IR. Chooses `#define` mask/shift
macros over packed bitfield structs deliberately: packed-struct bit ordering is
implementation-defined in C, so macros are the portable single-source contract
for firmware.

Per field it emits _MASK / _SHIFT / _WIDTH plus _GET(reg)/_SET(val) helpers; per
register an _OFFSET, an _ADDR (base+offset), and a _RESET; per enum a value macro.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ..ir import Field, Register, RegisterMap, build_ir
from ..loader import load_spec

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_TEMPLATE = "c_header.h.j2"


def _hex(value: int, data_width: int) -> str:
    """Fixed-width hex literal with an unsigned suffix, e.g. 0x0000000Fu."""
    digits = data_width // 4
    return f"0x{value:0{digits}X}u"


class FieldCView:
    def __init__(self, prefix: str, reg: Register, f: Field, data_width: int):
        base = f"{prefix}_{reg.name}" if f.implicit else f"{prefix}_{reg.name}_{f.name}"
        self.base = base
        self.name = f.name
        self.width = f.width
        self.shift = f.lsb
        self.mask = _hex(f.mask_shifted, data_width)
        self.access = f.access.name
        self.enums = [(f"{base}_{e.name}", _hex(e.value, data_width), e.description) for e in f.enums]


class RegCView:
    def __init__(self, prefix: str, reg: Register, data_width: int, addr_width: int):
        self.name = reg.name
        self.base = f"{prefix}_{reg.name}"
        self.offset = _hex(reg.offset, addr_width)
        self.offset_raw = reg.offset
        self.reset = _hex(reg.reset_value, data_width)
        self.description = reg.description
        self.fields = [FieldCView(prefix, reg, f, data_width) for f in reg.fields]


def _make_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def generate_c(rmap: RegisterMap, guard: str | None = None) -> str:
    block = rmap.block
    prefix = block.name.upper()
    guard = guard or f"{prefix}_REGS_H"
    dw = block.data_width
    registers = [RegCView(prefix, r, dw, block.addr_width) for r in rmap]

    env = _make_env()
    template = env.get_template(_TEMPLATE)
    return template.render(
        block=block,
        prefix=prefix,
        guard=guard,
        base_address=_hex(block.base_address, block.addr_width),
        registers=registers,
    )


def generate_c_from_spec(spec: dict, guard: str | None = None) -> str:
    return generate_c(build_ir(spec), guard)


def generate_c_from_file(path: str | Path, guard: str | None = None) -> str:
    return generate_c(build_ir(load_spec(path)), guard)
