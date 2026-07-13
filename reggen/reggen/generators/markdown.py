"""Markdown register-map documentation generator (M5).

Reads the IR directly (no symbol mangling needed) and renders a summary table
plus a per-register field table. This is the artifact the documentation team and
external readers actually see, so it leads with a scannable overview.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ..ir import Field, RegisterMap, build_ir
from ..loader import load_spec

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_TEMPLATE = "regmap.md.j2"


def _bits(f: Field) -> str:
    return f"{f.msb}:{f.lsb}" if f.width > 1 else f"{f.lsb}"


def _make_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["bits"] = _bits
    env.filters["hex"] = lambda v, dw=32: f"0x{v:0{dw // 4}X}"
    return env


def generate_md(rmap: RegisterMap) -> str:
    env = _make_env()
    template = env.get_template(_TEMPLATE)
    return template.render(block=rmap.block, registers=list(rmap))


def generate_md_from_spec(spec: dict) -> str:
    return generate_md(build_ir(spec))


def generate_md_from_file(path: str | Path) -> str:
    return generate_md(build_ir(load_spec(path)))
