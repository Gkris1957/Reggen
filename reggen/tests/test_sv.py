"""M3 SystemVerilog generator tests: structure, per-access logic, and a real
Verilator lint gate when the tool is present."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from reggen.generators.systemverilog import generate_sv_from_spec
from reggen.loader import parse_yaml, validate_spec

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
VERILATOR = shutil.which("verilator")


def sv_from(yaml_text: str) -> str:
    return generate_sv_from_spec(validate_spec(parse_yaml(yaml_text)))


def example_sv() -> str:
    return sv_from((EXAMPLES / "dma_lite.yaml").read_text())


# --- structure ----------------------------------------------------------------

def test_module_and_axi_ports_present():
    sv = example_sv()
    assert "module dma_csr_axil_csr" in sv
    for sig in ["s_axi_awvalid", "s_axi_wstrb", "s_axi_bresp", "s_axi_arvalid", "s_axi_rdata"]:
        assert sig in sv, sig
    assert sv.rstrip().endswith("`default_nettype wire")


def test_offset_localparams():
    sv = example_sv()
    assert "ADDR_CTRL = 'h0;" in sv
    assert "ADDR_STATUS = 'h4;" in sv
    assert "ADDR_INT_EN = 'h14;" in sv


def test_module_name_override():
    sv = generate_sv_from_spec(
        validate_spec(parse_yaml("block: {name: blk}\nregisters: [{name: R0, offset: 0, access: RW}]")),
        module_name="my_csr",
    )
    assert "module my_csr" in sv


# --- per-access logic ---------------------------------------------------------

def test_rw_field_byte_strobed_write():
    sv = example_sv()
    assert "CTRL_ENABLE_q <= (CTRL_ENABLE_q & ~wr_be[0]) | (s_axi_wdata[0] & wr_be[0]);" in sv


def test_w1c_hw_set_wins_sw_clears():
    sv = example_sv()
    # STATUS.DONE is W1C: clear on write-1, OR in the HW set input
    assert "STATUS_DONE_q & ~(s_axi_wdata[1] & wr_be[1])" in sv
    assert "| STATUS_DONE_set_i;" in sv


def test_w1s_hw_clear_wins_sw_sets():
    sv = example_sv()
    assert "CTRL_RESET_q | (s_axi_wdata[1] & wr_be[1])" in sv
    assert "& ~CTRL_RESET_clr_i;" in sv


def test_ro_field_reads_input_not_storage():
    sv = example_sv()
    assert "rd_data[0] = STATUS_BUSY_i;" in sv
    assert "STATUS_BUSY_q" not in sv  # RO has no storage


def test_implicit_field_full_width_storage():
    sv = example_sv()
    assert "reg [31:0] SRC_ADDR_q;" in sv
    assert "SRC_ADDR_q <= 32'h0;" in sv


def test_reset_value_in_rtl():
    sv = example_sv()
    assert "CTRL_BURST_LEN_q <= 8'h10;" in sv  # reset 0x10


def test_rc_read_clears():
    sv = sv_from("""
block: { name: blk }
registers:
  - name: R0
    offset: 0
    fields: [ { name: EVT, bits: "0", access: RC } ]
""")
    assert "rd_en && axi_araddr == ADDR_R0" in sv
    assert "| R0_EVT_set_i;" in sv


def test_wr_be_expansion_width():
    sv = sv_from("""
block: { name: blk, data_width: 16 }
registers: [ { name: R0, offset: 0, access: RW } ]
""")
    # 16-bit bus -> two byte strobes replicated
    assert "{{8{s_axi_wstrb[1]}}, {8{s_axi_wstrb[0]}}}" in sv


# --- the real gate: it must be valid SystemVerilog ---------------------------

@pytest.mark.skipif(VERILATOR is None, reason="verilator not installed")
def test_generated_sv_passes_verilator_lint(tmp_path):
    sv_file = tmp_path / "dma_csr.sv"
    sv_file.write_text(example_sv())
    result = subprocess.run(
        [VERILATOR, "--lint-only", "-Wall", "-Wno-DECLFILENAME", str(sv_file)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
