"""Violation analysis and heuristic pipeline-insertion candidates.

The heuristics deliberately stop at *candidates for designer review* — a
timing report alone cannot prove a register insertion is legal (it lacks
protocol and architectural context). Each suggestion says why the path is
slow and where a register stage would plausibly cut it.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .parser import TimingPath


@dataclass
class Suggestion:
    kind: str          # 'register-output' | 'pipeline-comb' | 'module-boundary'
    where: str
    rationale: str
    paths: list[TimingPath] = field(default_factory=list)

    @property
    def worst_slack(self) -> float:
        return min(p.slack for p in self.paths)


def _endpoint_group(p: TimingPath) -> str:
    """Group bus bits together: m_axi_wdata[3] -> m_axi_wdata[*]."""
    node = p.to_node
    if node.endswith("]") and "[" in node:
        return node[: node.rindex("[")] + "[*]"
    return node


def analyze(paths: list[TimingPath]) -> list[Suggestion]:
    violated = sorted((p for p in paths if p.violated), key=lambda p: p.slack)
    if not violated:
        return []

    groups: dict[str, list[TimingPath]] = defaultdict(list)
    for p in violated:
        groups[_endpoint_group(p)].append(p)

    suggestions: list[Suggestion] = []
    for endpoint, group in groups.items():
        rep = group[0]
        srcs = {p.module_of(p.from_node) for p in group}
        src_desc = ", ".join(sorted(srcs))

        if rep.endpoint_is_port:
            suggestions.append(Suggestion(
                kind="register-output",
                where=f"output port {endpoint}",
                rationale=(
                    f"{len(group)} violated path(s) from {src_desc} end at the "
                    f"top-level port {endpoint} — the path is dominated by "
                    "combinational logic driving an output. Insert an output "
                    "register stage (or require the consumer to register its "
                    "inputs) so the port is driven register-direct."
                ),
                paths=group,
            ))
        elif rep.logic_levels is not None and rep.logic_levels >= 4:
            suggestions.append(Suggestion(
                kind="pipeline-comb",
                where=f"{rep.from_node} -> {endpoint}",
                rationale=(
                    f"{rep.logic_levels} logic levels between registers "
                    f"({len(group)} path(s)). Split the combinational cone "
                    "with a pipeline register near its midpoint — typically "
                    "after the widest comparison or arithmetic step."
                ),
                paths=group,
            ))
        elif len({p.module_of(p.from_node) for p in group} |
                 {p.module_of(p.to_node) for p in group}) > 1:
            suggestions.append(Suggestion(
                kind="module-boundary",
                where=f"{src_desc} -> {rep.module_of(rep.to_node)}",
                rationale=(
                    f"{len(group)} violated path(s) cross a module boundary. "
                    "Register the signal at the producing module's output so "
                    "inter-module routing gets its own cycle."
                ),
                paths=group,
            ))
        else:
            suggestions.append(Suggestion(
                kind="pipeline-comb",
                where=f"{rep.from_node} -> {endpoint}",
                rationale=(
                    f"{len(group)} violated path(s); slack "
                    f"{rep.slack:.3f} ns. Review the combinational logic on "
                    "this path for a legal register insertion point."
                ),
                paths=group,
            ))

    suggestions.sort(key=lambda s: s.worst_slack)
    return suggestions


def render_report(paths: list[TimingPath], suggestions: list[Suggestion]) -> str:
    """Plain-text analysis report."""
    violated = [p for p in paths if p.violated]
    lines = [
        "STA Timing Analysis",
        "===================",
        f"paths parsed: {len(paths)}   violated: {len(violated)}",
    ]
    if not violated:
        lines.append("No setup violations — nothing to do.")
        return "\n".join(lines) + "\n"

    worst = min(p.slack for p in violated)
    lines.append(f"worst slack: {worst:.3f} ns")
    lines.append("")
    lines.append("Worst violated paths:")
    for p in sorted(violated, key=lambda q: q.slack)[:10]:
        lv = f"  levels={p.logic_levels}" if p.logic_levels is not None else ""
        lines.append(f"  {p.slack:8.3f} ns  {p.from_node}  ->  {p.to_node}{lv}")
    lines.append("")
    lines.append(f"Pipeline-insertion candidates ({len(suggestions)}), "
                 "for designer review:")
    for i, s in enumerate(suggestions, 1):
        lines.append(f"  {i}. [{s.kind}] {s.where}  (worst {s.worst_slack:.3f} ns)")
        lines.append(f"     {s.rationale}")
    return "\n".join(lines) + "\n"
