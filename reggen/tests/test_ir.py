"""M2 IR tests: packing math, implicit-field synthesis, access resolution."""

from __future__ import annotations

from pathlib import Path

from reggen import build_ir, load_ir
from reggen.ir import ACCESS_POLICIES
from reggen.loader import parse_yaml, validate_spec

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def ir_from(yaml_text: str):
    return build_ir(validate_spec(parse_yaml(yaml_text)))


# --- the example builds and exposes the right shape ---------------------------

def test_example_builds_ir():
    rmap = load_ir(EXAMPLES / "dma_lite.yaml")
    assert rmap.block.name == "dma_csr"
    assert len(rmap) == 6
    assert [r.name for r in rmap] == [
        "CTRL", "STATUS", "SRC_ADDR", "DST_ADDR", "LENGTH", "INT_EN"
    ]  # offset-sorted


def test_registers_are_offset_sorted():
    rmap = ir_from("""
block: { name: blk }
registers:
  - { name: HI, offset: 0x10, access: RW }
  - { name: LO, offset: 0x00, access: RW }
""")
    assert [r.name for r in rmap] == ["LO", "HI"]


# --- field packing math -------------------------------------------------------

def test_field_masks_and_width():
    rmap = ir_from("""
block: { name: blk }
registers:
  - name: R0
    offset: 0
    fields:
      - { name: F, bits: "5:3", access: RW, reset: 0x5 }
""")
    f = rmap.register("R0").fields[0]
    assert f.width == 3
    assert f.mask == 0b111
    assert f.mask_shifted == 0b111000
    assert f.reset == 0b101
    assert f.reset_shifted == 0b101000


def test_register_reset_aggregation():
    rmap = ir_from("""
block: { name: blk, data_width: 32 }
registers:
  - name: CTRL
    offset: 0
    fields:
      - { name: A, bits: "0",     access: RW, reset: 0x1 }
      - { name: B, bits: "11:4",  access: RW, reset: 0x10 }
""")
    reg = rmap.register("CTRL")
    # A=1 at bit0, B=0x10 at bit4 -> 0x10<<4 | 1 = 0x101
    assert reg.reset_value == (0x10 << 4) | 1
    assert reg.reset_mask == (0b1 | (0xFF << 4))


def test_reserved_bits_and_ranges():
    rmap = ir_from("""
block: { name: blk, data_width: 32 }
registers:
  - name: R0
    offset: 0
    fields:
      - { name: A, bits: "0", access: RW }
      - { name: B, bits: "7:4", access: RW }
""")
    reg = rmap.register("R0")
    # occupied: bit0, bits7:4. reserved: bits 3:1 and bits 31:8
    assert reg.reserved_ranges == ((31, 8), (3, 1))
    assert reg.reserved_mask == (((1 << 32) - 1) & ~(0b1 | (0xF << 4)))


def test_field_at_lookup():
    rmap = ir_from("""
block: { name: blk }
registers:
  - name: R0
    offset: 0
    fields:
      - { name: A, bits: "7:4", access: RW }
""")
    reg = rmap.register("R0")
    assert reg.field_at(5).name == "A"
    assert reg.field_at(0) is None


# --- implicit whole-register field synthesis ----------------------------------

def test_implicit_field_synthesized():
    rmap = ir_from("""
block: { name: blk, data_width: 32 }
registers:
  - { name: SRC, offset: 0, access: RW, reset: 0xDEADBEEF }
""")
    reg = rmap.register("SRC")
    assert len(reg.fields) == 1
    f = reg.fields[0]
    assert f.implicit is True
    assert f.name == "SRC"
    assert (f.msb, f.lsb) == (31, 0)
    assert f.width == 32
    assert reg.reset_value == 0xDEADBEEF


def test_explicit_fields_not_marked_implicit():
    rmap = ir_from("""
block: { name: blk }
registers:
  - name: R0
    offset: 0
    fields: [ { name: F, bits: "0", access: RW } ]
""")
    assert rmap.register("R0").fields[0].implicit is False


# --- access policy resolution -------------------------------------------------

def test_access_resolved_to_policy_object():
    rmap = ir_from("""
block: { name: blk }
registers:
  - name: R0
    offset: 0
    fields:
      - { name: DONE, bits: "0", access: W1C }
      - { name: BUSY, bits: "1", access: RO }
""")
    reg = rmap.register("R0")
    done = reg.field_at(0)
    busy = reg.field_at(1)
    assert done.access.on_write == "clear"
    assert done.access.readable and done.access.hw_writable
    assert busy.access.sw_writable is False
    assert busy.access.on_read == "none"


def test_rc_clears_on_read():
    pol = ACCESS_POLICIES["RC"]
    assert pol.on_read == "clear"
    assert pol.sw_writable is False


def test_default_access_is_rw():
    rmap = ir_from("""
block: { name: blk }
registers:
  - name: R0
    offset: 0
    fields: [ { name: F, bits: "0" } ]
""")
    assert rmap.register("R0").fields[0].access.name == "RW"


# --- block-level derived values ----------------------------------------------

def test_block_stride_and_span():
    rmap = ir_from("""
block: { name: blk, data_width: 32, base_address: 0x1000 }
registers:
  - { name: A, offset: 0x00, access: RW }
  - { name: B, offset: 0x04, access: RW }
""")
    assert rmap.block.stride_bytes == 4
    assert rmap.block.base_address == 0x1000
    assert rmap.address_span == 0x08  # last offset 0x04 + 4 bytes


def test_enums_carried_into_ir():
    rmap = ir_from("""
block: { name: blk }
registers:
  - name: R0
    offset: 0
    fields:
      - name: DIR
        bits: "0"
        access: RW
        enum:
          - { name: M2D, value: 0 }
          - { name: D2M, value: 1 }
""")
    f = rmap.register("R0").field_at(0)
    assert [(e.name, e.value) for e in f.enums] == [("M2D", 0), ("D2M", 1)]
