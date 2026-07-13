"""M5 C-header generator tests: macros, and a real gcc compile gate."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from reggen.generators.cheader import generate_c_from_spec
from reggen.loader import parse_yaml, validate_spec

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
GCC = shutil.which("gcc") or shutil.which("cc")


def c_from(yaml_text: str) -> str:
    return generate_c_from_spec(validate_spec(parse_yaml(yaml_text)))


def example_c() -> str:
    return c_from((EXAMPLES / "dma_lite.yaml").read_text())


# --- structure ----------------------------------------------------------------

def test_include_guard_and_base():
    h = example_c()
    assert "#ifndef DMA_CSR_REGS_H" in h
    assert "#define DMA_CSR_REGS_H" in h
    assert "#endif /* DMA_CSR_REGS_H */" in h
    assert "#define DMA_CSR_BASE 0x000u" in h


def test_register_offset_addr_reset():
    h = example_c()
    assert "#define DMA_CSR_CTRL_OFFSET" in h
    assert "(DMA_CSR_BASE + 0x000u)" in h
    assert "#define DMA_CSR_CTRL_RESET" in h and "0x00000100u" in h


def test_field_mask_shift_width():
    h = example_c()
    assert "DMA_CSR_CTRL_BURST_LEN_MASK" in h and "0x00000FF0u" in h
    assert "DMA_CSR_CTRL_BURST_LEN_SHIFT" in h and " 4u" in h
    assert "DMA_CSR_CTRL_BURST_LEN_WIDTH" in h and " 8u" in h


def test_get_set_helper_macros():
    h = example_c()
    assert "DMA_CSR_CTRL_ENABLE_GET(reg)" in h
    assert "DMA_CSR_CTRL_ENABLE_SET(val)" in h


def test_enum_value_defines():
    h = example_c()
    assert "DMA_CSR_CTRL_DIRECTION_MEM_TO_DEV" in h
    assert "DMA_CSR_CTRL_DIRECTION_DEV_TO_MEM" in h


def test_implicit_field_no_name_doubling():
    h = example_c()
    # SRC_ADDR implicit whole-reg field must be DMA_CSR_SRC_ADDR_*, not _SRC_ADDR_SRC_ADDR_*
    assert "DMA_CSR_SRC_ADDR_MASK" in h
    assert "SRC_ADDR_SRC_ADDR" not in h


def test_guard_override():
    h = generate_c_from_spec(
        validate_spec(parse_yaml("block: {name: blk}\nregisters: [{name: R0, offset: 0, access: RW}]")),
        guard="MY_GUARD_H",
    )
    assert "#ifndef MY_GUARD_H" in h


# --- the real gate: it must compile, and the macros must behave ---------------

@pytest.mark.skipif(GCC is None, reason="no C compiler available")
def test_header_compiles_and_macros_work(tmp_path):
    (tmp_path / "dma_csr.h").write_text(example_c())
    main_c = tmp_path / "use.c"
    main_c.write_text(
        '#include "dma_csr.h"\n'
        "#include <assert.h>\n"
        "int main(void){\n"
        "  uint32_t r = DMA_CSR_CTRL_ENABLE_SET(1u) | DMA_CSR_CTRL_BURST_LEN_SET(0x10u);\n"
        "  assert(r == (DMA_CSR_CTRL_RESET | 1u));\n"     # 0x100 (BURST_LEN=0x10) | ENABLE
        "  assert(DMA_CSR_CTRL_BURST_LEN_GET(r) == 0x10u);\n"
        "  assert(DMA_CSR_CTRL_ENABLE_GET(r) == 1u);\n"
        "  return 0;\n"
        "}\n"
    )
    exe = tmp_path / "use"
    build = subprocess.run(
        [GCC, "-I", str(tmp_path), "-Wall", "-Wextra", "-std=c11", str(main_c), "-o", str(exe)],
        capture_output=True, text=True,
    )
    assert build.returncode == 0, build.stderr
    run = subprocess.run([str(exe)], capture_output=True, text=True)
    assert run.returncode == 0, "runtime assertion failed in generated-macro usage"
