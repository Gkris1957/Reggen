"""Intermediate representation (IR) — the typed object model generators consume.

M1 hands us a *validated* raw dict. M2 turns that into immutable dataclasses with
all field-packing math pre-computed, so no generator ever re-parses bit specs or
recomputes masks. Two normalizations matter most:

  1. A register with no ``fields`` is given ONE synthesized whole-width field, so
     downstream code never has to handle the "implicit field" case.
  2. Access strings (RW/W1C/RC/...) become AccessPolicy objects with behavior
     flags (readable / sw_writable / on_write / on_read), so generators emit
     hardware from semantics rather than string matching.

Everything here assumes the spec already passed validate_spec(); build_ir does
not re-validate. Use load_ir() for the validated path.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from pathlib import Path

from ._helpers import parse_bits, to_int
from .loader import load_spec

DEFAULT_DATA_WIDTH = 32
DEFAULT_ADDR_WIDTH = 32


# --------------------------------------------------------------------------- #
# Access policy: one string -> a bundle of behavior flags.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class AccessPolicy:
    """Behavioral description of a field access type.

    on_write: what a software write does -- 'store' (normal), 'clear' (W1C),
              'set' (W1S), or 'none' (ignored / read-only).
    on_read:  side effect of a software read -- 'none' or 'clear' (RC).
    hw_writable: hardware (the design logic) drives this field's value.
    """

    name: str
    readable: bool
    sw_writable: bool
    hw_writable: bool
    on_write: str  # 'store' | 'clear' | 'set' | 'none'
    on_read: str  # 'none' | 'clear'


# The 8 v0 policies. Keys match the schema enum exactly.
ACCESS_POLICIES: dict[str, AccessPolicy] = {
    "RW":   AccessPolicy("RW",   readable=True,  sw_writable=True,  hw_writable=False, on_write="store", on_read="none"),
    "RO":   AccessPolicy("RO",   readable=True,  sw_writable=False, hw_writable=True,  on_write="none",  on_read="none"),
    "WO":   AccessPolicy("WO",   readable=False, sw_writable=True,  hw_writable=False, on_write="store", on_read="none"),
    "W1C":  AccessPolicy("W1C",  readable=True,  sw_writable=True,  hw_writable=True,  on_write="clear", on_read="none"),
    "W1S":  AccessPolicy("W1S",  readable=True,  sw_writable=True,  hw_writable=True,  on_write="set",   on_read="none"),
    "RW1C": AccessPolicy("RW1C", readable=True,  sw_writable=True,  hw_writable=True,  on_write="clear", on_read="none"),
    "RW1S": AccessPolicy("RW1S", readable=True,  sw_writable=True,  hw_writable=True,  on_write="set",   on_read="none"),
    "RC":   AccessPolicy("RC",   readable=True,  sw_writable=False, hw_writable=True,  on_write="none",  on_read="clear"),
}

DEFAULT_ACCESS = "RW"


# --------------------------------------------------------------------------- #
# Leaf nodes.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class EnumConst:
    name: str
    value: int
    description: str = ""


@dataclass(frozen=True)
class Field:
    """One bit-field with all packing math pre-computed."""

    name: str
    msb: int
    lsb: int
    access: AccessPolicy
    reset: int  # field-local reset (already validated to fit in `width`)
    description: str = ""
    enums: tuple[EnumConst, ...] = ()
    # True when this field was synthesized to cover a register that declared no
    # explicit fields (whole-register access/reset shorthand).
    implicit: bool = False

    @property
    def width(self) -> int:
        return self.msb - self.lsb + 1

    @property
    def mask(self) -> int:
        """Unshifted mask, e.g. width 3 -> 0b111."""
        return (1 << self.width) - 1

    @property
    def mask_shifted(self) -> int:
        """Mask positioned at the field's bit offset, e.g. bits 5:3 -> 0b111000."""
        return self.mask << self.lsb

    @property
    def reset_shifted(self) -> int:
        """Field reset positioned within the register word."""
        return self.reset << self.lsb


@dataclass(frozen=True)
class Register:
    name: str
    offset: int
    width: int
    fields: tuple[Field, ...]
    description: str = ""

    @property
    def reset_value(self) -> int:
        """Aggregate power-on value of the whole register word."""
        v = 0
        for f in self.fields:
            v |= f.reset_shifted
        return v

    @property
    def reset_mask(self) -> int:
        """Bits that have a defined reset (i.e. are covered by some field)."""
        m = 0
        for f in self.fields:
            m |= f.mask_shifted
        return m

    @property
    def reserved_mask(self) -> int:
        """Bits in the register word not claimed by any field."""
        return ((1 << self.width) - 1) & ~self.reset_mask

    @property
    def reserved_ranges(self) -> tuple[tuple[int, int], ...]:
        """Reserved bits as (msb, lsb) runs, MSB-first — handy for tie-offs."""
        occupied = self.reset_mask
        runs: list[tuple[int, int]] = []
        bit = 0
        while bit < self.width:
            if occupied & (1 << bit):
                bit += 1
                continue
            start = bit
            while bit < self.width and not (occupied & (1 << bit)):
                bit += 1
            runs.append((bit - 1, start))
        runs.reverse()
        return tuple(runs)

    def field_at(self, bit: int) -> Field | None:
        for f in self.fields:
            if f.lsb <= bit <= f.msb:
                return f
        return None


@dataclass(frozen=True)
class Block:
    name: str
    data_width: int
    addr_width: int
    base_address: int = 0
    description: str = ""

    @property
    def stride_bytes(self) -> int:
        """Natural byte stride of one bus word."""
        return self.data_width // 8


@dataclass(frozen=True)
class RegisterMap:
    """Top of the IR: a block plus its registers, offset-sorted."""

    block: Block
    registers: tuple[Register, ...] = dc_field(default_factory=tuple)

    def __iter__(self):
        return iter(self.registers)

    def __len__(self) -> int:
        return len(self.registers)

    @property
    def address_span(self) -> int:
        """Bytes from base to the end of the last register word."""
        if not self.registers:
            return 0
        last = self.registers[-1]
        return last.offset + last.width // 8

    def register(self, name: str) -> Register | None:
        for r in self.registers:
            if r.name == name:
                return r
        return None


# --------------------------------------------------------------------------- #
# Builder: validated dict -> IR.
# --------------------------------------------------------------------------- #
def _build_enums(raw_field: dict) -> tuple[EnumConst, ...]:
    return tuple(
        EnumConst(
            name=e["name"],
            value=to_int(e["value"]),
            description=e.get("description", ""),
        )
        for e in raw_field.get("enum", [])
    )


def _build_field(raw: dict) -> Field:
    msb, lsb = parse_bits(raw["bits"])
    return Field(
        name=raw["name"],
        msb=msb,
        lsb=lsb,
        access=ACCESS_POLICIES[raw.get("access", DEFAULT_ACCESS)],
        reset=to_int(raw.get("reset", 0)),
        description=raw.get("description", ""),
        enums=_build_enums(raw),
    )


def _synthesize_field(raw_reg: dict, width: int) -> Field:
    """Build the implicit whole-width field for a register with no `fields`."""
    return Field(
        name=raw_reg["name"],
        msb=width - 1,
        lsb=0,
        access=ACCESS_POLICIES[raw_reg.get("access", DEFAULT_ACCESS)],
        reset=to_int(raw_reg.get("reset", 0)),
        description=raw_reg.get("description", ""),
        implicit=True,
    )


def _build_register(raw: dict, data_width: int) -> Register:
    width = raw.get("width", data_width)
    if raw.get("fields"):
        fields = tuple(_build_field(f) for f in raw["fields"])
        fields = tuple(sorted(fields, key=lambda f: f.lsb))
    else:
        fields = (_synthesize_field(raw, width),)
    return Register(
        name=raw["name"],
        offset=to_int(raw["offset"]),
        width=width,
        fields=fields,
        description=raw.get("description", ""),
    )


def build_ir(spec: dict) -> RegisterMap:
    """Convert a *validated* spec dict into a RegisterMap. Does not re-validate."""
    raw_block = spec["block"]
    data_width = raw_block.get("data_width", DEFAULT_DATA_WIDTH)
    block = Block(
        name=raw_block["name"],
        data_width=data_width,
        addr_width=raw_block.get("addr_width", DEFAULT_ADDR_WIDTH),
        base_address=to_int(raw_block.get("base_address", 0)),
        description=raw_block.get("description", ""),
    )
    registers = tuple(
        sorted(
            (_build_register(r, data_width) for r in spec["registers"]),
            key=lambda r: r.offset,
        )
    )
    return RegisterMap(block=block, registers=registers)


def load_ir(path: str | Path) -> RegisterMap:
    """Validate a spec file (M1) and build its IR (M2) in one call."""
    return build_ir(load_spec(path))
