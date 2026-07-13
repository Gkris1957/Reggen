"""Error types raised by reggen's loader and validator."""

from __future__ import annotations


class ReggenError(Exception):
    """Base class for all reggen errors."""


class SpecParseError(ReggenError):
    """Raised when the YAML cannot be parsed at all (syntax error)."""


class SchemaValidationError(ReggenError):
    """Raised when the spec violates the JSON Schema (structural check).

    Carries a list of human-readable messages so the CLI can print every
    structural problem at once rather than one-at-a-time.
    """

    def __init__(self, messages: list[str]):
        self.messages = messages
        super().__init__(self._format(messages))

    @staticmethod
    def _format(messages: list[str]) -> str:
        head = f"{len(messages)} schema error(s):"
        return "\n".join([head, *(f"  - {m}" for m in messages)])


class SemanticValidationError(ReggenError):
    """Raised for problems JSON Schema cannot express.

    Examples: overlapping fields, misaligned offsets, reset values that do
    not fit, duplicate names, bit ranges outside the register width.
    """

    def __init__(self, messages: list[str]):
        self.messages = messages
        super().__init__(self._format(messages))

    @staticmethod
    def _format(messages: list[str]) -> str:
        head = f"{len(messages)} semantic error(s):"
        return "\n".join([head, *(f"  - {m}" for m in messages)])
