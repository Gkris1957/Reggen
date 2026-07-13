"""reggen — one YAML register-map spec, many generated artifacts.

M1 surface: load and validate a spec.
    >>> from reggen import load_spec
    >>> spec = load_spec("examples/dma_lite.yaml")
"""

from __future__ import annotations

from .errors import (
    ReggenError,
    SchemaValidationError,
    SemanticValidationError,
    SpecParseError,
)
from .ir import (
    AccessPolicy,
    Block,
    EnumConst,
    Field,
    Register,
    RegisterMap,
    build_ir,
    load_ir,
)
from .loader import load_schema, load_spec, parse_yaml, validate_spec

__version__ = "0.1.0"

__all__ = [
    "load_spec",
    "validate_spec",
    "parse_yaml",
    "load_schema",
    "build_ir",
    "load_ir",
    "RegisterMap",
    "Block",
    "Register",
    "Field",
    "EnumConst",
    "AccessPolicy",
    "ReggenError",
    "SpecParseError",
    "SchemaValidationError",
    "SemanticValidationError",
    "__version__",
]
