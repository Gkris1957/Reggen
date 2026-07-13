"""Command-line entry point. M1 ships the `validate` subcommand.

    reggen validate examples/dma_lite.yaml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .errors import ReggenError
from .loader import load_spec


def _cmd_validate(args: argparse.Namespace) -> int:
    ok = True
    for spec_path in args.specs:
        try:
            spec = load_spec(spec_path)
        except ReggenError as exc:
            ok = False
            print(f"FAIL  {spec_path}", file=sys.stderr)
            print(exc, file=sys.stderr)
            continue
        nregs = len(spec["registers"])
        print(f"OK    {spec_path}  (block '{spec['block']['name']}', {nregs} registers)")
    return 0 if ok else 1


def _cmd_gen(args: argparse.Namespace) -> int:
    from .generators.cheader import generate_c_from_file
    from .generators.markdown import generate_md_from_file
    from .generators.systemverilog import generate_sv_from_file
    from .generators.uvm import generate_uvm_from_file

    try:
        if args.target == "sv":
            text = generate_sv_from_file(args.spec, module_name=args.module)
        elif args.target == "uvm":
            text = generate_uvm_from_file(args.spec, pkg_name=args.module)
        elif args.target == "c":
            text = generate_c_from_file(args.spec, guard=args.module)
        else:  # md
            text = generate_md_from_file(args.spec)
    except ReggenError as exc:
        print(f"FAIL  {args.spec}", file=sys.stderr)
        print(exc, file=sys.stderr)
        return 1

    if args.output:
        Path(args.output).write_text(text)
        print(f"wrote {args.output}  ({args.target}, from {args.spec})")
    else:
        sys.stdout.write(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="reggen", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_val = sub.add_parser("validate", help="validate one or more YAML specs")
    p_val.add_argument("specs", nargs="+", type=Path, help="spec file(s) to check")
    p_val.set_defaults(func=_cmd_validate)

    p_gen = sub.add_parser("gen", help="generate an artifact from a spec")
    p_gen.add_argument("spec", type=Path, help="spec file")
    p_gen.add_argument("--target", choices=["sv", "uvm", "c", "md"], default="sv", help="output kind")
    p_gen.add_argument("-o", "--output", type=Path, help="output file (default: stdout)")
    p_gen.add_argument("--module", help="override module (sv) / package (uvm) / include-guard (c) name")
    p_gen.set_defaults(func=_cmd_gen)

    p_nl = sub.add_parser(
        "nl2yaml",
        help="convert an English register description to validated YAML (Claude API)",
    )
    src = p_nl.add_mutually_exclusive_group(required=True)
    src.add_argument("description", nargs="?", help="the description text")
    src.add_argument("--file", type=Path, help="read the description from a file")
    p_nl.add_argument("-o", "--output", type=Path, help="output file (default: stdout)")
    p_nl.add_argument("--model", default=None, help="Claude model id override")
    p_nl.add_argument("--max-retries", type=int, default=3,
                      help="validation-correction rounds (default 3)")
    p_nl.set_defaults(func=_cmd_nl2yaml)

    return parser


def _cmd_nl2yaml(args: argparse.Namespace) -> int:
    from .nl2yaml import DEFAULT_MODEL, Nl2YamlError, make_client, nl_to_yaml

    description = args.file.read_text() if args.file else args.description
    try:
        client = make_client()
        result = nl_to_yaml(
            description,
            client,
            model=args.model or DEFAULT_MODEL,
            max_retries=args.max_retries,
        )
    except Nl2YamlError as exc:
        print(f"FAIL  could not produce a valid spec: {exc}", file=sys.stderr)
        if exc.last_yaml:
            print("--- last attempt ---", file=sys.stderr)
            print(exc.last_yaml, file=sys.stderr)
        return 1
    except ReggenError as exc:
        print(f"FAIL  {exc}", file=sys.stderr)
        return 1

    if args.output:
        args.output.write_text(result.yaml_text + "\n")
        nregs = len(result.spec["registers"])
        print(f"wrote {args.output}  (validated: block "
              f"'{result.spec['block']['name']}', {nregs} registers, "
              f"{result.attempts} attempt(s))")
    else:
        sys.stdout.write(result.yaml_text + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
