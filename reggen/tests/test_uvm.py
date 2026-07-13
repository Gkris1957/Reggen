"""M4 UVM register-block generator tests.

Fast structural + mapping asserts always run. The real gate — compiling the
generated package against UVM with QuestaSim's vlog — is opt-in via
REGGEN_UVM_COMPILE=1 because building uvm_pkg takes ~30s.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from reggen.generators.uvm import generate_uvm_from_spec
from reggen.loader import parse_yaml, validate_spec

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
VLOG = shutil.which("vlog")
_QROOT = "/home/goutham-krishna/intelFPGA_lite/21.1/questa_fse"
_UVM_SRC = Path(_QROOT) / "verilog_src" / "uvm-1.2" / "src"


def uvm_from(yaml_text: str) -> str:
    return generate_uvm_from_spec(validate_spec(parse_yaml(yaml_text)))


def example_uvm() -> str:
    return uvm_from((EXAMPLES / "dma_lite.yaml").read_text())


# --- structure ----------------------------------------------------------------

def test_package_and_block_class():
    uvm = example_uvm()
    assert "package dma_csr_reg_pkg;" in uvm
    assert "import uvm_pkg::*;" in uvm
    assert '`include "uvm_macros.svh"' in uvm
    assert "class dma_csr_reg_block extends uvm_reg_block;" in uvm
    assert "endpackage" in uvm


def test_one_reg_class_per_register():
    uvm = example_uvm()
    for cls in ["CTRL_reg", "STATUS_reg", "SRC_ADDR_reg", "INT_EN_reg"]:
        assert f"class {cls} extends uvm_reg;" in uvm


def test_include_guard():
    uvm = example_uvm()
    assert "`ifndef DMA_CSR_REG_PKG_SV" in uvm
    assert "`define DMA_CSR_REG_PKG_SV" in uvm
    assert "`endif // DMA_CSR_REG_PKG_SV" in uvm


def test_map_creation_and_add_reg():
    uvm = example_uvm()
    assert 'create_map("default_map", \'h0, 4, UVM_LITTLE_ENDIAN);' in uvm
    assert "default_map.add_reg(CTRL, 'h0, \"RW\");" in uvm
    assert "default_map.add_reg(INT_EN, 'h14, \"RW\");" in uvm
    assert "lock_model();" in uvm


# --- configure() argument correctness (the classic trap) ---------------------

def test_configure_arg_order_rw_field():
    uvm = example_uvm()
    # ENABLE: size=1 lsb=0 access=RW volatile=0 reset=0 has_reset=1 is_rand=1 indiv=0
    assert 'ENABLE.configure(this, 1, 0, "RW", 0, 1\'h0, 1, 1, 0);' in uvm


def test_burst_len_size_lsb_reset():
    uvm = example_uvm()
    # BURST_LEN [11:4] reset 0x10 -> size=8 lsb=4 reset=8'h10
    assert 'BURST_LEN.configure(this, 8, 4, "RW", 0, 8\'h10, 1, 1, 0);' in uvm


def test_ro_field_volatile_and_not_rand():
    uvm = example_uvm()
    # BUSY is RO: volatile=1 (HW-driven), is_rand=0 (SW cannot write)
    assert 'BUSY.configure(this, 1, 0, "RO", 1, 1\'h0, 1, 0, 0);' in uvm


def test_w1c_maps_and_is_volatile():
    uvm = example_uvm()
    # DONE is W1C: access "W1C", volatile=1, is_rand=1
    assert 'DONE.configure(this, 1, 1, "W1C", 1, 1\'h0, 1, 1, 0);' in uvm


def test_access_policy_folding():
    # RW1C -> W1C, RW1S -> W1S, RC -> RC
    uvm = uvm_from("""
block: { name: blk }
registers:
  - name: R0
    offset: 0
    fields:
      - { name: A, bits: "0", access: RW1C }
      - { name: B, bits: "1", access: RW1S }
      - { name: C, bits: "2", access: RC }
""")
    assert '"W1C"' in uvm and '"W1S"' in uvm and '"RC"' in uvm


def test_register_rights_readonly():
    # a register whose only field is RO must be added as "RO"
    uvm = uvm_from("""
block: { name: blk }
registers:
  - name: STAT
    offset: 0
    fields: [ { name: X, bits: "0", access: RO } ]
""")
    assert 'add_reg(STAT, \'h0, "RO");' in uvm


def test_pkg_name_override():
    uvm = generate_uvm_from_spec(
        validate_spec(parse_yaml("block: {name: blk}\nregisters: [{name: R0, offset: 0, access: RW}]")),
        pkg_name="custom_pkg",
    )
    assert "package custom_pkg;" in uvm


# --- the real gate: compile against UVM with QuestaSim -----------------------

@pytest.mark.skipif(
    VLOG is None or not _UVM_SRC.exists() or os.environ.get("REGGEN_UVM_COMPILE") != "1",
    reason="set REGGEN_UVM_COMPILE=1 with QuestaSim+UVM available to run the compile gate",
)
def test_generated_uvm_compiles(tmp_path):
    pkg = tmp_path / "dma_reg_pkg.sv"
    pkg.write_text(example_uvm())
    subprocess.run(["vlib", "work"], cwd=tmp_path, check=True, capture_output=True)
    result = subprocess.run(
        ["vlog", "-sv", "-quiet", f"+incdir+{_UVM_SRC}",
         str(_UVM_SRC / "uvm_pkg.sv"), str(pkg)],
        cwd=tmp_path, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
