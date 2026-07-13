"""Wrapper that runs the cocotb functional sim of the generated CSR from pytest.

Opt-in via REGGEN_FUNCTIONAL=1 (it recompiles the DUT under Verilator, ~10-20s).
The sim itself lives in tests/functional/ and is also runnable directly with
`make` there.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

FUNC = Path(__file__).resolve().parent / "functional"
VERILATOR = shutil.which("verilator")

try:
    import cocotb  # noqa: F401
    HAVE_COCOTB = True
except ImportError:
    HAVE_COCOTB = False


@pytest.mark.skipif(
    os.environ.get("REGGEN_FUNCTIONAL") != "1"
    or VERILATOR is None
    or not HAVE_COCOTB,
    reason="set REGGEN_FUNCTIONAL=1 with Verilator+cocotb to run the functional sim",
)
def test_generated_csr_behaves():
    subprocess.run(["make", "clean"], cwd=FUNC, capture_output=True)
    proc = subprocess.run(
        ["make"], cwd=FUNC, capture_output=True, text=True, timeout=600
    )
    results = FUNC / "results.xml"
    assert results.exists(), f"sim did not produce results.xml\n{proc.stdout}\n{proc.stderr}"

    tree = ET.parse(results)
    failed = [
        tc.get("name")
        for tc in tree.iter("testcase")
        if tc.find("failure") is not None or tc.find("error") is not None
    ]
    assert not failed and proc.returncode == 0, (
        f"functional failures: {failed}\n{proc.stdout[-2000:]}"
    )
