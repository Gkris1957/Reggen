"""Timing-report parsers.

Two supported formats, auto-detected:
  * Quartus ``report_timing`` text output (``quartus_sta -t ... -file x.rpt``)
  * OpenSTA ``report_checks`` text output

Both produce the same normalized TimingPath records so the analyzer and the
LLM layer are format-agnostic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class TimingPath:
    slack: float                     # ns; negative = violated
    from_node: str
    to_node: str
    launch_clock: str = ""
    latch_clock: str = ""
    logic_levels: int | None = None
    data_delay: float | None = None  # ns of data-path delay
    source: str = ""                 # "quartus" | "opensta"
    raw: str = field(default="", repr=False)

    @property
    def violated(self) -> bool:
        return self.slack < 0

    @property
    def endpoint_is_port(self) -> bool:
        """Heuristic: endpoints without a hierarchy separator are top ports."""
        return "|" not in self.to_node and "/" not in self.to_node

    def module_of(self, node: str) -> str:
        """Leading instance path of a node, e.g. 'dma_channel:u_ch0'."""
        for sep in ("|", "/"):
            if sep in node:
                return node.split(sep)[0]
        return "<top>"


# --------------------------------------------------------------------------- #
# Quartus
# --------------------------------------------------------------------------- #
_Q_PATH_HDR = re.compile(
    r"Path #\d+: Setup slack is (-?\d+\.\d+)\s*(\(VIOLATED\))?"
)
_Q_ROW = re.compile(r"^;\s*(?P<key>[A-Za-z ][A-Za-z /()]*?)\s+;\s*(?P<val>.*?)\s*;\s*$")


def parse_quartus(text: str) -> list[TimingPath]:
    paths: list[TimingPath] = []
    # split into per-path sections
    sections = _Q_PATH_HDR.split(text)
    # split() yields: [pre, slack1, viol1, body1, slack2, viol2, body2, ...]
    for i in range(1, len(sections) - 2, 3):
        slack = float(sections[i])
        body = sections[i + 2]
        props: dict[str, str] = {}
        for line in body.splitlines():
            m = _Q_ROW.match(line.strip())
            if m:
                key = m.group("key").strip()
                if key not in props:          # first table (Path Summary) wins
                    props[key] = m.group("val").strip()
        # statistics-table rows have extra columns; use dedicated extractors
        lv = re.search(r";\s*Number of Logic Levels\s*;[^;]*;\s*(\d+)\s*;", body)
        levels = int(lv.group(1)) if lv else None
        dd = re.search(r";\s*Data Delay\s*;\s*(-?\d+\.\d+)", body)
        data_delay = float(dd.group(1)) if dd else None
        paths.append(
            TimingPath(
                slack=slack,
                from_node=props.get("From Node", "?"),
                to_node=props.get("To Node", "?"),
                launch_clock=props.get("Launch Clock", ""),
                latch_clock=props.get("Latch Clock", ""),
                logic_levels=levels,
                data_delay=data_delay,
                source="quartus",
                raw=body,
            )
        )
    return paths


# --------------------------------------------------------------------------- #
# OpenSTA
# --------------------------------------------------------------------------- #
_O_START = re.compile(r"^Startpoint:\s*(\S+)")
_O_END = re.compile(r"^Endpoint:\s*(\S+)")
_O_CLK = re.compile(r"clocked by (\S+?)\)")
_O_SLACK = re.compile(r"^\s*(-?\d+\.\d+)\s+slack\s*(\(VIOLATED\)|\(MET\))?")


def parse_opensta(text: str) -> list[TimingPath]:
    paths: list[TimingPath] = []
    current: dict | None = None
    body_lines: list[str] = []
    for line in text.splitlines():
        m = _O_START.match(line.strip())
        if m:
            current = {"from": m.group(1), "launch": "", "latch": ""}
            clk = _O_CLK.search(line)
            if clk:
                current["launch"] = clk.group(1)
            body_lines = [line]
            continue
        if current is None:
            continue
        body_lines.append(line)
        m = _O_END.match(line.strip())
        if m:
            current["to"] = m.group(1)
            clk = _O_CLK.search(line)
            if clk:
                current["latch"] = clk.group(1)
            continue
        m = _O_SLACK.match(line)
        if m and "to" in current:
            paths.append(
                TimingPath(
                    slack=float(m.group(1)),
                    from_node=current["from"],
                    to_node=current["to"],
                    launch_clock=current["launch"],
                    latch_clock=current["latch"],
                    source="opensta",
                    raw="\n".join(body_lines),
                )
            )
            current = None
    return paths


# --------------------------------------------------------------------------- #
# auto-detect
# --------------------------------------------------------------------------- #
def parse_report(text: str) -> list[TimingPath]:
    """Auto-detect the report format and parse it."""
    if _Q_PATH_HDR.search(text):
        return parse_quartus(text)
    if "Startpoint:" in text:
        return parse_opensta(text)
    raise ValueError(
        "unrecognized timing report format (expected Quartus report_timing "
        "or OpenSTA report_checks text output)"
    )
