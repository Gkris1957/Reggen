"""M6 golden-file regression: every (spec x target) must match its snapshot.

This is the CI gate that stops a template edit from silently changing generated
RTL / headers / docs. Outputs are deterministic (no timestamps embedded), so a
diff always means a real change.

To (re)generate goldens after an *intended* change:
    REGGEN_UPDATE_GOLDEN=1 pytest tests/test_golden.py
then review the git diff before committing.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from reggen.generators.cheader import generate_c_from_file
from reggen.generators.markdown import generate_md_from_file
from reggen.generators.systemverilog import generate_sv_from_file
from reggen.generators.uvm import generate_uvm_from_file

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
GOLDEN = Path(__file__).resolve().parent / "golden"

# spec stems under examples/ that get snapshotted
SPECS = ["dma_lite", "timer"]

# target -> (generator, golden filename pattern)
TARGETS = {
    "sv": (generate_sv_from_file, "{stem}.sv"),
    "uvm": (generate_uvm_from_file, "{stem}.uvm.sv"),
    "c": (generate_c_from_file, "{stem}.h"),
    "md": (generate_md_from_file, "{stem}.md"),
}

UPDATE = os.environ.get("REGGEN_UPDATE_GOLDEN") == "1"

CASES = [(s, t) for s in SPECS for t in TARGETS]


@pytest.mark.parametrize("stem,target", CASES, ids=[f"{s}-{t}" for s, t in CASES])
def test_golden(stem: str, target: str):
    generate, pattern = TARGETS[target]
    produced = generate(EXAMPLES / f"{stem}.yaml")
    golden = GOLDEN / pattern.format(stem=stem)

    if UPDATE:
        GOLDEN.mkdir(parents=True, exist_ok=True)
        golden.write_text(produced)
        pytest.skip(f"updated golden {golden.name}")

    assert golden.exists(), (
        f"missing golden {golden.name} — run `REGGEN_UPDATE_GOLDEN=1 pytest` to create it"
    )
    expected = golden.read_text()
    assert produced == expected, (
        f"{target} output for {stem} drifted from golden {golden.name}. "
        f"If the change is intended, run `REGGEN_UPDATE_GOLDEN=1 pytest` and review the diff."
    )
