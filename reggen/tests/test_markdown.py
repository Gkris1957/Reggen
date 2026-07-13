"""M5 Markdown docs generator tests: summary table, field tables, enums."""

from __future__ import annotations

from pathlib import Path

from reggen.generators.markdown import generate_md_from_spec
from reggen.loader import parse_yaml, validate_spec

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def md_from(yaml_text: str) -> str:
    return generate_md_from_spec(validate_spec(parse_yaml(yaml_text)))


def example_md() -> str:
    return md_from((EXAMPLES / "dma_lite.yaml").read_text())


def test_title_and_block_properties():
    md = example_md()
    assert md.startswith("# dma_csr register map")
    assert "| Data width | 32 bits |" in md
    assert "| Base address | 0x000 |" in md


def test_summary_table_lists_every_register():
    md = example_md()
    for name in ["CTRL", "STATUS", "SRC_ADDR", "DST_ADDR", "LENGTH", "INT_EN"]:
        assert f"[{name}](#{name.lower()})" in md


def test_summary_row_has_offset_and_reset():
    md = example_md()
    assert "| 0x000 | [CTRL](#ctrl) | 0x00000100 |" in md
    assert "| 0x014 | [INT_EN](#int_en) | 0x00000000 |" in md


def test_per_register_field_table():
    md = example_md()
    # CTRL.BURST_LEN row: bits 11:4, RW, reset 0x10
    assert "| 11:4 | BURST_LEN | RW | 0x10 |" in md
    # single-bit field prints one number, not N:N
    assert "| 0 | ENABLE | RW | 0x0 |" in md


def test_access_column_reflects_policy():
    md = example_md()
    assert "| 1 | DONE | W1C |" in md
    assert "| 0 | BUSY | RO |" in md


def test_enum_values_rendered():
    md = example_md()
    assert "*DIRECTION values:*" in md
    assert "**MEM_TO_DEV**" in md
    assert "**DEV_TO_MEM**" in md


def test_implicit_field_appears_full_width():
    md = example_md()
    # SRC_ADDR whole-register implicit field spans 31:0
    assert "| 31:0 | SRC_ADDR | RW |" in md
