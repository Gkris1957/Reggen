"""Load and fully validate a reggen YAML spec.

Pipeline:  YAML parse  ->  JSON Schema (structural)  ->  semantic checks.
Each stage raises a distinct error type so callers can report precisely.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from .errors import SchemaValidationError, SpecParseError
from .validate import validate_semantics

_SCHEMA_PATH = Path(__file__).with_name("schema.json")


@lru_cache(maxsize=1)
def load_schema() -> dict:
    """Return the bundled JSON Schema (cached)."""
    return json.loads(_SCHEMA_PATH.read_text())


def parse_yaml(text: str) -> dict:
    """Parse YAML text into a dict, normalizing parse errors."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SpecParseError(f"YAML parse error: {exc}") from exc
    if not isinstance(data, dict):
        raise SpecParseError(
            "spec must be a YAML mapping at the top level "
            f"(got {type(data).__name__})"
        )
    return data


def validate_structure(spec: dict) -> None:
    """Run JSON Schema validation, collecting *all* errors at once."""
    validator = Draft202012Validator(load_schema())
    messages: list[str] = []
    for err in sorted(validator.iter_errors(spec), key=lambda e: list(e.path)):
        location = "/".join(str(p) for p in err.path) or "<root>"
        messages.append(f"{location}: {err.message}")
    if messages:
        raise SchemaValidationError(messages)


def validate_spec(spec: dict) -> dict:
    """Run structural then semantic validation on an already-parsed spec."""
    validate_structure(spec)
    validate_semantics(spec)
    return spec


def load_spec(path: str | Path) -> dict:
    """Load, parse, and fully validate a spec file. Returns the raw dict.

    The rich intermediate representation is built in M2 (ir.py); M1 guarantees
    that whatever this returns is structurally and semantically sound.
    """
    path = Path(path)
    try:
        text = path.read_text()
    except OSError as exc:
        raise SpecParseError(f"cannot read spec file '{path}': {exc}") from exc
    spec = parse_yaml(text)
    return validate_spec(spec)
