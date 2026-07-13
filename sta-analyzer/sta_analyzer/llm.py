"""Claude-powered review of the parsed timing data (optional layer).

Sends the normalized violations + heuristic candidates to Claude and returns
a markdown review: root-cause reading of the critical paths, an opinion on
each candidate, and RTL-level suggestions. The client is injected for
testability; `make_client()` builds the real one.

The static instructions carry a cache_control breakpoint so repeated runs
(e.g. after each synthesis iteration) reuse the cached prefix.
"""

from __future__ import annotations

from .analyze import Suggestion
from .parser import TimingPath

DEFAULT_MODEL = "claude-opus-4-8"

_SYSTEM = """\
You are a senior STA/timing-closure engineer reviewing setup violations from
a synthesized design. You receive normalized critical-path records and
heuristic pipeline-insertion candidates produced by a parser.

Write a markdown review with these sections:
## Root cause
Read the paths structurally (start/end points, logic levels, common
endpoints) and explain what actually limits Fmax — not per-path noise, the
patterns.
## Candidate assessment
For each heuristic candidate: agree or disagree, and say what the RTL change
would look like and what it risks (latency, protocol rules such as AXI
signal-stability requirements, area).
## Recommended plan
An ordered, minimal set of changes to close timing, most effective first.

Ground every claim in the provided data; if the data cannot support a
conclusion, say so. These are recommendations for designer review — flag
anything that needs architectural context the report cannot show."""


def _format_paths(paths: list[TimingPath], limit: int = 20) -> str:
    rows = []
    for p in sorted(paths, key=lambda q: q.slack)[:limit]:
        rows.append(
            f"- slack {p.slack:.3f} ns | {p.from_node} -> {p.to_node}"
            + (f" | logic levels {p.logic_levels}" if p.logic_levels is not None else "")
            + (f" | data delay {p.data_delay:.3f}" if p.data_delay is not None else "")
        )
    return "\n".join(rows)


def _format_suggestions(suggestions: list[Suggestion]) -> str:
    return "\n".join(
        f"- [{s.kind}] {s.where} (worst {s.worst_slack:.3f} ns): {s.rationale}"
        for s in suggestions
    )


def review(
    paths: list[TimingPath],
    suggestions: list[Suggestion],
    client,
    model: str = DEFAULT_MODEL,
    context: str = "",
) -> str:
    """Return Claude's markdown review of the violations and candidates."""
    violated = [p for p in paths if p.violated]
    user = (
        f"Design context: {context or 'not provided'}\n\n"
        f"Violated setup paths ({len(violated)} of {len(paths)} parsed):\n"
        f"{_format_paths(violated)}\n\n"
        f"Heuristic candidates:\n{_format_suggestions(suggestions)}"
    )
    response = client.messages.create(
        model=model,
        max_tokens=8192,
        thinking={"type": "adaptive"},
        system=[
            {
                "type": "text",
                "text": _SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user}],
    )
    return next(
        (b.text for b in response.content if getattr(b, "type", "") == "text"),
        "",
    )


def make_client():
    """Build a real Anthropic client (import deferred: optional dependency)."""
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError(
            "--llm needs the anthropic package: pip install 'sta-analyzer[llm]'"
        ) from exc
    return anthropic.Anthropic()
