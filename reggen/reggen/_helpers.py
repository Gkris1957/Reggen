"""Small parsing helpers shared by the loader and validator.

These operate on the *raw validated dict* (post JSON Schema, pre-IR). The rich
object model lives in M2's ir.py; here we only need enough parsing to run the
semantic checks.
"""

from __future__ import annotations


def to_int(value) -> int:
    """Coerce a uint spec value (int or '0x..' string) to a Python int.

    The JSON Schema guarantees the shape, so this never sees garbage; it only
    has to bridge the YAML-as-string hex convention.
    """
    if isinstance(value, bool):  # bool is an int subclass — reject it explicitly
        raise TypeError("boolean is not a valid integer value")
    if isinstance(value, int):
        return value
    return int(value, 16)


def parse_bits(bits: str) -> tuple[int, int]:
    """Parse a 'MSB:LSB' or single-bit 'N' spec into an (msb, lsb) pair.

    Schema has already enforced the ``^[0-9]+(:[0-9]+)?$`` shape, so split is safe.
    """
    if ":" in bits:
        msb_s, lsb_s = bits.split(":", 1)
        return int(msb_s), int(lsb_s)
    n = int(bits)
    return n, n


def field_width(msb: int, lsb: int) -> int:
    return msb - lsb + 1


def register_width(register: dict, data_width: int) -> int:
    """Resolved width of a register: explicit ``width`` else block ``data_width``."""
    return register.get("width", data_width)
