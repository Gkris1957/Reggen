"""Natural-language → reggen YAML frontend (Claude API).

Converts a plain-English register-map description into YAML that passes
reggen's full 3-stage validation. The core design is the **validator in the
loop**: Claude's output is run through parse_yaml + validate_spec, and on any
failure every error message is fed back for self-correction, up to a retry
budget. The output of this module is therefore never an unvalidated guess —
it is either a spec that passed the same gate the generators use, or an error.

The Anthropic client is injected (constructor argument) so the loop is fully
unit-testable without an API key; the CLI builds a real client.

Requires the optional dependency:  pip install "reggen[nl]"
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .errors import ReggenError
from .loader import load_schema, parse_yaml, validate_spec

DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_MAX_RETRIES = 3

# The system prompt is deliberately static and assembled deterministically:
# it is the cacheable prefix. The volatile user description and the error
# feedback turns come after it, so retries within the loop (and repeated CLI
# invocations within the cache TTL) hit the prompt cache.
_EXAMPLE_YAML = """\
block:
  name: uart_csr
  description: Control/status registers for a UART.
  data_width: 32
  addr_width: 8
  base_address: 0x0000

registers:
  - name: CTRL
    offset: 0x00
    description: Control register.
    fields:
      - name: ENABLE
        bits: "0"
        access: RW
        reset: 0x0
        description: 1 = enable the UART.
      - name: PARITY
        bits: "2:1"
        access: RW
        reset: 0x0
        enum:
          - { name: NONE, value: 0 }
          - { name: ODD,  value: 1 }
          - { name: EVEN, value: 2 }
  - name: STATUS
    offset: 0x04
    fields:
      - name: TX_BUSY
        bits: "0"
        access: RO
        description: Transmitter busy.
      - name: RX_OVERFLOW
        bits: "1"
        access: W1C
        reset: 0x0
        description: Set by HW on overflow; write 1 to clear.
  - name: BAUD_DIV
    offset: 0x08
    access: RW
    reset: 0x0
    description: Baud-rate divider (whole-register field).
"""


def build_system_prompt() -> str:
    """Assemble the static system prompt: rules + JSON schema + example."""
    schema_json = json.dumps(load_schema(), indent=2, sort_keys=True)
    return f"""\
You convert plain-English register-map descriptions into YAML for `reggen`,
a hardware register-file generator. Output ONLY the YAML document — no code
fences, no prose, no explanations before or after.

Hard rules of the spec language (violations are rejected by a validator):
- Top level has exactly `block` and `registers`.
- A register uses EITHER `fields` OR register-level `access`/`reset`
  (implicit whole-width field) — never both.
- Offsets are byte addresses: unique, aligned to the register byte width,
  and they must fit in `addr_width` bits.
- Field `bits` are "MSB:LSB" or a single "N"; fields must not overlap and
  must fit in the register width.
- Access is one of RW RO WO W1C W1S RW1C RW1S RC. Status flags set by
  hardware and cleared by software are W1C; command bits software sets and
  hardware clears are W1S; hardware-driven read-only values are RO.
- Reset values and enum values must fit in the field width. RO fields do
  not need a reset.
- Names must be valid C/SystemVerilog identifiers (UPPER_SNAKE is
  conventional). Quote bit specs ("15:8") and write hex as 0x-strings.

Conventions when the description leaves details open:
- data_width 32 unless stated; choose the smallest addr_width that fits
  the register map; pack registers at consecutive word-aligned offsets.
- Give every register and non-obvious field a short `description`.
- Interrupt-style blocks usually pair a W1C status register with an RW
  enable register.

The full JSON Schema for the output:

{schema_json}

A complete example of valid output:

{_EXAMPLE_YAML}"""


@dataclass
class Nl2YamlResult:
    yaml_text: str
    spec: dict
    attempts: int
    error_history: list[str] = field(default_factory=list)


class Nl2YamlError(ReggenError):
    """Raised when Claude cannot produce a valid spec within the retry budget."""

    def __init__(self, attempts: int, error_history: list[str], last_yaml: str):
        self.attempts = attempts
        self.error_history = error_history
        self.last_yaml = last_yaml
        super().__init__(
            f"no valid spec after {attempts} attempt(s); "
            f"last validation error:\n{error_history[-1] if error_history else '<none>'}"
        )


def _strip_fences(text: str) -> str:
    """Tolerate a fenced code block despite the no-fences instruction."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        # drop opening fence (possibly ```yaml) and a trailing fence
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines)
    return stripped


def nl_to_yaml(
    description: str,
    client,
    model: str = DEFAULT_MODEL,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> Nl2YamlResult:
    """Convert an English description to validated reggen YAML.

    `client` is an anthropic.Anthropic-compatible object (injected for
    testability). Raises Nl2YamlError if no valid spec is produced within
    `max_retries` correction rounds.
    """
    system = [
        {
            "type": "text",
            "text": build_system_prompt(),
            # Stable prefix marked cacheable. Note: Opus-tier models only cache
            # prefixes >= 4096 tokens; the current prompt (~1.6K tokens) is
            # below that, so this is a no-cost future-proofing marker that
            # activates as the schema/examples grow (or on lower-minimum models).
            "cache_control": {"type": "ephemeral"},
        }
    ]
    messages = [{"role": "user", "content": description}]
    error_history: list[str] = []
    yaml_text = ""

    for attempt in range(1, max_retries + 2):   # initial try + max_retries fixes
        response = client.messages.create(
            model=model,
            max_tokens=8192,
            thinking={"type": "adaptive"},
            system=system,
            messages=messages,
        )
        raw = next(
            (b.text for b in response.content if getattr(b, "type", "") == "text"),
            "",
        )
        yaml_text = _strip_fences(raw)

        try:
            spec = validate_spec(parse_yaml(yaml_text))
            return Nl2YamlResult(
                yaml_text=yaml_text,
                spec=spec,
                attempts=attempt,
                error_history=error_history,
            )
        except ReggenError as exc:
            error_history.append(str(exc))
            # feed the model its own output + every validator error, and retry
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "That YAML failed reggen validation with the following "
                        f"error(s):\n\n{exc}\n\n"
                        "Fix every listed problem and output the corrected "
                        "YAML document only."
                    ),
                }
            )

    raise Nl2YamlError(len(error_history), error_history, yaml_text)


def make_client():
    """Build a real Anthropic client (import deferred: optional dependency)."""
    try:
        import anthropic
    except ImportError as exc:
        raise ReggenError(
            "the nl2yaml command needs the anthropic package: "
            'pip install "reggen[nl]"'
        ) from exc
    return anthropic.Anthropic()
