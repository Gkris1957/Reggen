"""sta-analyzer tests.

The Quartus fixture is REAL output from `quartus_sta report_timing` on the
dma-controller v2 build (I/O-budget-constrained run, 10 violated paths). The
OpenSTA fixture is synthetic but format-faithful (no OpenSTA install here).
The LLM layer is tested with a fake client — no API key required.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sta_analyzer import analyze, parse_report, render_report
from sta_analyzer.llm import review

FIXTURES = Path(__file__).parent / "fixtures"
QUARTUS = (FIXTURES / "quartus_dma.rpt").read_text()
OPENSTA = (FIXTURES / "opensta_sample.rpt").read_text()


# ---- Quartus parsing (real data) ----------------------------------------------

def test_quartus_parses_all_paths():
    paths = parse_report(QUARTUS)
    assert len(paths) == 10
    assert all(p.source == "quartus" for p in paths)
    assert all(p.violated for p in paths)


def test_quartus_worst_path_fields():
    worst = min(parse_report(QUARTUS), key=lambda p: p.slack)
    assert worst.slack == pytest.approx(-3.415)
    assert worst.to_node == "m_axi_wdata[3]"
    assert "u_ch0" in worst.from_node
    assert worst.launch_clock == "clk" and worst.latch_clock == "clk"
    assert worst.logic_levels == 2
    assert worst.data_delay == pytest.approx(3.185)


def test_quartus_endpoint_is_port():
    paths = parse_report(QUARTUS)
    assert all(p.endpoint_is_port for p in paths)   # all end at m_axi_wdata[*]


# ---- OpenSTA parsing (synthetic fixture) --------------------------------------

def test_opensta_parses_met_and_violated():
    paths = parse_report(OPENSTA)
    assert len(paths) == 2
    met, viol = paths
    assert met.slack == pytest.approx(5.79) and not met.violated
    assert viol.slack == pytest.approx(-0.79) and viol.violated
    assert viol.from_node == "u_ch1/wr_words_reg_5_"
    assert viol.to_node == "u_ch1/wr_burst_reg_7_"
    assert viol.launch_clock == "clk"


def test_unknown_format_raises():
    with pytest.raises(ValueError):
        parse_report("this is not a timing report")


# ---- analysis heuristics -------------------------------------------------------

def test_analysis_groups_bus_bits_and_suggests_output_register():
    paths = parse_report(QUARTUS)
    suggestions = analyze(paths)
    # all 10 real violations end at m_axi_wdata[*] -> ONE grouped suggestion
    assert len(suggestions) == 1
    s = suggestions[0]
    assert s.kind == "register-output"
    assert "m_axi_wdata[*]" in s.where
    assert len(s.paths) == 10
    assert s.worst_slack == pytest.approx(-3.415)


def test_analysis_no_violations_is_empty():
    paths = [p for p in parse_report(OPENSTA) if not p.violated]
    assert analyze(paths) == []


def test_report_rendering():
    paths = parse_report(QUARTUS)
    out = render_report(paths, analyze(paths))
    assert "violated: 10" in out
    assert "worst slack: -3.415" in out
    assert "register-output" in out
    assert "designer review" in out


# ---- LLM layer (fake client) ---------------------------------------------------

class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class FakeClient:
    def __init__(self, reply):
        self.reply = reply
        self.last_kwargs = None
        self.messages = self

    def create(self, **kwargs):
        self.last_kwargs = kwargs

        class R:
            content = [_Block(self.reply)]
        return R()


def test_llm_review_request_shape():
    paths = parse_report(QUARTUS)
    suggestions = analyze(paths)
    client = FakeClient("## Root cause\nOutput paths dominate.")
    out = review(paths, suggestions, client, context="2ch AXI DMA @100MHz")
    assert out.startswith("## Root cause")
    kw = client.last_kwargs
    assert kw["model"] == "claude-opus-4-8"
    assert kw["thinking"] == {"type": "adaptive"}
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    user = kw["messages"][0]["content"]
    assert "m_axi_wdata" in user           # parsed paths made it into the prompt
    assert "register-output" in user       # and the heuristic candidates
    assert "2ch AXI DMA @100MHz" in user   # and the design context
