# sta-analyzer

Parse STA signoff reports, surface critical-path violations, and propose
**pipeline-insertion candidates for designer review** — optionally reviewed by
Claude for root-cause analysis and an ordered closure plan.

Supported report formats (auto-detected):

- **Quartus** `report_timing` text output (`quartus_sta -t ... -file x.rpt`)
- **OpenSTA** `report_checks` text output

## Use

```bash
pip install -e .                 # heuristics only, no API needed
sta-analyze path/to/report.rpt   # exit 2 if violations found (CI-friendly)

pip install -e ".[llm]"          # add the Claude review layer
export ANTHROPIC_API_KEY=...     # or `ant auth login`
sta-analyze report.rpt --llm --context "2-channel AXI DMA, 100 MHz, Cyclone V" -o review.md
```

## What it does

1. **Parse** — normalizes every path to slack / start / end / clocks / logic
   levels / data delay (`sta_analyzer/parser.py`).
2. **Analyze** (`analyze.py`) — groups violations (bus bits like
   `m_axi_wdata[3]`, `[20]`, ... collapse to `m_axi_wdata[*]`), then proposes
   candidates by structure:
   - paths ending at a top-level port → *register the output*
   - deep combinational cones (≥4 logic levels) → *pipeline the cone midpoint*
   - cross-module paths → *register at the module boundary*
3. **Review** (`--llm`, `llm.py`) — sends the normalized paths + candidates to
   Claude (`claude-opus-4-8`, adaptive thinking, cached system prompt) for a
   markdown review: root cause, per-candidate assessment (including protocol
   risks like AXI signal-stability rules), and an ordered closure plan.

Suggestions are deliberately *candidates*: a timing report alone cannot prove
an insertion is legal — that judgment (and the LLM's review) is for the
designer.

## Provenance

`tests/fixtures/quartus_dma.rpt` is **real** Quartus output from the
[dma-controller](../dma-controller/) v2 synthesis run (the I/O-budget
characterization pass with 10 violated paths). On that data the analyzer
groups all 10 violations into a single candidate — *register the
`m_axi_wdata` output* — matching the manually-derived conclusion from the
timing-closure work. `opensta_sample.rpt` is synthetic but format-faithful
(no OpenSTA install was available).

The LLM layer is fully unit-tested with an injected fake client; no API key
is needed to run `pytest`.
