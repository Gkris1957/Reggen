"""sta-analyzer — timing-report parsing, violation analysis, and
LLM-assisted pipeline-insertion recommendations."""

from .analyze import Suggestion, analyze, render_report
from .parser import TimingPath, parse_opensta, parse_quartus, parse_report

__version__ = "0.1.0"

__all__ = [
    "TimingPath",
    "parse_report",
    "parse_quartus",
    "parse_opensta",
    "analyze",
    "render_report",
    "Suggestion",
    "__version__",
]
