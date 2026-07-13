"""sta-analyze — parse a timing report, surface violations, propose
pipeline-insertion candidates; optionally have Claude review them.

    sta-analyze report.rpt
    sta-analyze report.rpt --llm --context "2-channel AXI DMA, 100 MHz" -o review.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .analyze import analyze, render_report
from .parser import parse_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sta-analyze", description=__doc__)
    parser.add_argument("report", type=Path, help="Quartus or OpenSTA timing report")
    parser.add_argument("--llm", action="store_true",
                        help="add a Claude review of the findings")
    parser.add_argument("--context", default="",
                        help="one-line design context for the LLM review")
    parser.add_argument("--model", default=None, help="Claude model id override")
    parser.add_argument("-o", "--output", type=Path,
                        help="write the report/review to a file")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        paths = parse_report(args.report.read_text())
    except (OSError, ValueError) as exc:
        print(f"FAIL  {exc}", file=sys.stderr)
        return 1

    suggestions = analyze(paths)
    out = render_report(paths, suggestions)

    if args.llm:
        from .llm import DEFAULT_MODEL, make_client, review

        out += "\n" + review(
            paths,
            suggestions,
            make_client(),
            model=args.model or DEFAULT_MODEL,
            context=args.context,
        ) + "\n"

    if args.output:
        args.output.write_text(out)
        print(f"wrote {args.output}")
    else:
        sys.stdout.write(out)

    return 2 if any(p.violated for p in paths) else 0


if __name__ == "__main__":
    raise SystemExit(main())
