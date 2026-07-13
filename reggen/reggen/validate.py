"""Semantic validation — the checks JSON Schema cannot express.

Runs on the raw validated dict (after structural JSON Schema validation). Every
problem is collected with a path-like location so the user sees *all* errors at
once, then raised together as a single SemanticValidationError.

Design decisions baked into v0 (each is enforced here, not in the schema):
  * A register is described EITHER by ``fields`` OR by register-level
    ``access``/``reset`` (implicit whole-width field) — never both. One source
    of truth per register.
  * Register width must not exceed the bus ``data_width``. Multi-bus-beat
    registers are a v1 feature.
  * Offsets are byte addresses, must be unique and aligned to the register's
    byte width, and must fit in ``addr_width`` bits.
  * Field bit ranges must satisfy msb >= lsb, lie within the register width,
    and not overlap any sibling field.
  * Reset and enum values must fit in their target width.
"""

from __future__ import annotations

from ._helpers import (
    field_width,
    parse_bits,
    register_width,
    to_int,
)
from .errors import SemanticValidationError

DEFAULT_DATA_WIDTH = 32
DEFAULT_ADDR_WIDTH = 32


def validate_semantics(spec: dict) -> None:
    """Run all semantic checks. Raises SemanticValidationError if any fail."""
    errors: list[str] = []

    block = spec["block"]
    data_width = block.get("data_width", DEFAULT_DATA_WIDTH)
    addr_width = block.get("addr_width", DEFAULT_ADDR_WIDTH)
    bus_bytes = data_width // 8
    addr_limit = 1 << addr_width

    # --- block-level ---------------------------------------------------------
    if "base_address" in block:
        base = to_int(block["base_address"])
        if base % bus_bytes != 0:
            errors.append(
                f"block '{block['name']}': base_address 0x{base:x} is not "
                f"aligned to the {bus_bytes}-byte data bus"
            )

    # --- register-level ------------------------------------------------------
    seen_reg_names: dict[str, int] = {}
    seen_offsets: dict[int, str] = {}

    for ri, reg in enumerate(spec["registers"]):
        rname = reg["name"]
        loc = f"register '{rname}'"

        # duplicate register names
        if rname in seen_reg_names:
            errors.append(
                f"{loc}: duplicate register name (also at index "
                f"{seen_reg_names[rname]})"
            )
        else:
            seen_reg_names[rname] = ri

        rwidth = register_width(reg, data_width)
        if rwidth > data_width:
            errors.append(
                f"{loc}: width {rwidth} exceeds bus data_width {data_width} "
                f"(multi-beat registers are not supported in v0)"
            )

        # offset alignment + uniqueness + range
        offset = to_int(reg["offset"])
        reg_bytes = rwidth // 8
        if offset % reg_bytes != 0:
            errors.append(
                f"{loc}: offset 0x{offset:x} is not aligned to the register's "
                f"{reg_bytes}-byte width"
            )
        if offset >= addr_limit:
            errors.append(
                f"{loc}: offset 0x{offset:x} does not fit in addr_width "
                f"{addr_width} bits (limit 0x{addr_limit:x})"
            )
        if offset in seen_offsets:
            errors.append(
                f"{loc}: offset 0x{offset:x} collides with register "
                f"'{seen_offsets[offset]}'"
            )
        else:
            seen_offsets[offset] = rname

        has_fields = "fields" in reg and reg["fields"]
        has_reg_access = "access" in reg
        has_reg_reset = "reset" in reg

        if has_fields:
            # one source of truth: no register-level access/reset alongside fields
            if has_reg_access:
                errors.append(
                    f"{loc}: register-level 'access' is ambiguous when 'fields' "
                    f"are present — put access on each field"
                )
            if has_reg_reset:
                errors.append(
                    f"{loc}: register-level 'reset' is ambiguous when 'fields' "
                    f"are present — put reset on each field"
                )
            errors.extend(_validate_fields(reg, rwidth, loc))
        else:
            # implicit whole-width single field — reset must fit
            if has_reg_reset:
                reset = to_int(reg["reset"])
                if reset >= (1 << rwidth):
                    errors.append(
                        f"{loc}: reset 0x{reset:x} does not fit in {rwidth} bits"
                    )

    if errors:
        raise SemanticValidationError(errors)


def _validate_fields(reg: dict, rwidth: int, loc: str) -> list[str]:
    """Validate one register's fields: ranges, overlap, resets, enums."""
    errors: list[str] = []
    seen_field_names: dict[str, int] = {}
    occupied: list[tuple[int, int, str]] = []  # (lsb, msb, field name)

    for fi, fld in enumerate(reg["fields"]):
        fname = fld["name"]
        floc = f"{loc}, field '{fname}'"

        if fname in seen_field_names:
            errors.append(
                f"{floc}: duplicate field name within register "
                f"(also at index {seen_field_names[fname]})"
            )
        else:
            seen_field_names[fname] = fi

        msb, lsb = parse_bits(fld["bits"])
        if msb < lsb:
            errors.append(
                f"{floc}: bit range '{fld['bits']}' has msb < lsb "
                f"(write it as MSB:LSB)"
            )
            continue  # range is nonsense; skip dependent checks
        if msb >= rwidth:
            errors.append(
                f"{floc}: bits '{fld['bits']}' exceed register width {rwidth} "
                f"(max bit index {rwidth - 1})"
            )

        # overlap against earlier fields
        for o_lsb, o_msb, o_name in occupied:
            if lsb <= o_msb and o_lsb <= msb:
                errors.append(
                    f"{floc}: bits '{fld['bits']}' overlap field '{o_name}' "
                    f"[{o_msb}:{o_lsb}]"
                )
                break
        occupied.append((lsb, msb, fname))

        width = field_width(msb, lsb)

        if "reset" in fld:
            reset = to_int(fld["reset"])
            if reset >= (1 << width):
                errors.append(
                    f"{floc}: reset 0x{reset:x} does not fit in {width} bit(s)"
                )

        if "enum" in fld:
            errors.extend(_validate_enum(fld, width, floc))

    return errors


def _validate_enum(fld: dict, width: int, floc: str) -> list[str]:
    errors: list[str] = []
    seen_names: dict[str, int] = {}
    seen_values: dict[int, str] = {}
    for ei, item in enumerate(fld["enum"]):
        ename = item["name"]
        if ename in seen_names:
            errors.append(f"{floc}: duplicate enum name '{ename}'")
        else:
            seen_names[ename] = ei

        value = to_int(item["value"])
        if value >= (1 << width):
            errors.append(
                f"{floc}: enum '{ename}' value 0x{value:x} does not fit in "
                f"{width} bit(s)"
            )
        if value in seen_values:
            errors.append(
                f"{floc}: enum '{ename}' value 0x{value:x} duplicates enum "
                f"'{seen_values[value]}'"
            )
        else:
            seen_values[value] = ename
    return errors
