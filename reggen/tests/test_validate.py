"""M1 validation tests: the example loads, and every guard rail fires."""

from __future__ import annotations

from pathlib import Path

import pytest

from reggen import (
    SchemaValidationError,
    SemanticValidationError,
    SpecParseError,
)
from reggen.loader import parse_yaml, validate_spec

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def check(yaml_text: str):
    """Parse + fully validate inline YAML; returns the spec or raises."""
    return validate_spec(parse_yaml(yaml_text))


# --- the bundled example is the golden 'this must always pass' case ----------

def test_example_spec_is_valid():
    spec = check((EXAMPLES / "dma_lite.yaml").read_text())
    assert spec["block"]["name"] == "dma_csr"
    assert len(spec["registers"]) == 6


MINIMAL = """
block: { name: blk, data_width: 32, addr_width: 8 }
registers:
  - name: R0
    offset: 0x00
    fields:
      - { name: F0, bits: "0", access: RW, reset: 0 }
"""


def test_minimal_spec_is_valid():
    assert check(MINIMAL)["registers"][0]["name"] == "R0"


# --- parse / structural failures ---------------------------------------------

def test_top_level_must_be_mapping():
    with pytest.raises(SpecParseError):
        parse_yaml("- just\n- a\n- list\n")


def test_missing_registers_is_structural():
    with pytest.raises(SchemaValidationError):
        check("block: { name: blk }\n")


def test_bad_identifier_is_structural():
    with pytest.raises(SchemaValidationError):
        check("""
block: { name: "9bad" }
registers:
  - { name: R0, offset: 0 }
""")


def test_unknown_access_is_structural():
    with pytest.raises(SchemaValidationError):
        check("""
block: { name: blk }
registers:
  - name: R0
    offset: 0
    fields: [ { name: F, bits: "0", access: NOPE } ]
""")


# --- semantic failures: each guard rail in isolation -------------------------

def sem_msgs(yaml_text: str) -> list[str]:
    with pytest.raises(SemanticValidationError) as ei:
        check(yaml_text)
    return ei.value.messages


def test_duplicate_register_name():
    msgs = sem_msgs("""
block: { name: blk }
registers:
  - { name: R0, offset: 0x00, access: RW }
  - { name: R0, offset: 0x04, access: RW }
""")
    assert any("duplicate register name" in m for m in msgs)


def test_offset_collision():
    msgs = sem_msgs("""
block: { name: blk }
registers:
  - { name: R0, offset: 0x00, access: RW }
  - { name: R1, offset: 0x00, access: RW }
""")
    assert any("collides" in m for m in msgs)


def test_offset_misaligned():
    msgs = sem_msgs("""
block: { name: blk, data_width: 32 }
registers:
  - { name: R0, offset: 0x02, access: RW }
""")
    assert any("not aligned" in m for m in msgs)


def test_offset_exceeds_addr_width():
    msgs = sem_msgs("""
block: { name: blk, data_width: 32, addr_width: 4 }
registers:
  - { name: R0, offset: 0x40, access: RW }
""")
    assert any("does not fit in addr_width" in m for m in msgs)


def test_field_exceeds_register_width():
    msgs = sem_msgs("""
block: { name: blk, data_width: 32 }
registers:
  - name: R0
    offset: 0
    fields: [ { name: F, bits: "32", access: RW } ]
""")
    assert any("exceed register width" in m for m in msgs)


def test_reversed_bit_range():
    msgs = sem_msgs("""
block: { name: blk }
registers:
  - name: R0
    offset: 0
    fields: [ { name: F, bits: "0:7", access: RW } ]
""")
    assert any("msb < lsb" in m for m in msgs)


def test_overlapping_fields():
    msgs = sem_msgs("""
block: { name: blk }
registers:
  - name: R0
    offset: 0
    fields:
      - { name: A, bits: "7:0", access: RW }
      - { name: B, bits: "4:2", access: RW }
""")
    assert any("overlap" in m for m in msgs)


def test_field_reset_too_wide():
    msgs = sem_msgs("""
block: { name: blk }
registers:
  - name: R0
    offset: 0
    fields: [ { name: F, bits: "1:0", access: RW, reset: 0x4 } ]
""")
    assert any("does not fit in 2 bit" in m for m in msgs)


def test_register_reset_too_wide():
    msgs = sem_msgs("""
block: { name: blk, data_width: 8 }
registers:
  - { name: R0, offset: 0, width: 8, access: RW, reset: 0x100 }
""")
    assert any("does not fit in 8 bits" in m for m in msgs)


def test_access_and_fields_are_ambiguous():
    msgs = sem_msgs("""
block: { name: blk }
registers:
  - name: R0
    offset: 0
    access: RW
    fields: [ { name: F, bits: "0", access: RW } ]
""")
    assert any("register-level 'access' is ambiguous" in m for m in msgs)


def test_register_width_exceeds_data_width():
    msgs = sem_msgs("""
block: { name: blk, data_width: 32 }
registers:
  - { name: R0, offset: 0, width: 64, access: RW }
""")
    assert any("exceeds bus data_width" in m for m in msgs)


def test_enum_value_too_wide():
    msgs = sem_msgs("""
block: { name: blk }
registers:
  - name: R0
    offset: 0
    fields:
      - name: F
        bits: "1:0"
        access: RW
        enum: [ { name: BIG, value: 0x4 } ]
""")
    assert any("does not fit" in m for m in msgs)


def test_duplicate_enum_value():
    msgs = sem_msgs("""
block: { name: blk }
registers:
  - name: R0
    offset: 0
    fields:
      - name: F
        bits: "1:0"
        access: RW
        enum:
          - { name: A, value: 1 }
          - { name: B, value: 1 }
""")
    assert any("duplicates enum" in m for m in msgs)


def test_all_errors_reported_at_once():
    # two independent problems -> both surface in one raise
    msgs = sem_msgs("""
block: { name: blk, data_width: 32 }
registers:
  - { name: R0, offset: 0x02, access: RW }
  - { name: R0, offset: 0x04, access: RW }
""")
    assert any("not aligned" in m for m in msgs)
    assert any("duplicate register name" in m for m in msgs)
