"""nl2yaml tests — the validation-correction loop, exercised with a fake
Anthropic client so no API key or network is needed."""

from __future__ import annotations

import pytest

from reggen.nl2yaml import Nl2YamlError, build_system_prompt, nl_to_yaml

VALID_YAML = """\
block:
  name: timer_csr
  data_width: 32
  addr_width: 8
registers:
  - name: CTRL
    offset: 0x00
    fields:
      - { name: ENABLE, bits: "0", access: RW, reset: 0x0 }
"""

# overlapping fields -> semantic validation error
INVALID_YAML = """\
block:
  name: timer_csr
  data_width: 32
  addr_width: 8
registers:
  - name: CTRL
    offset: 0x00
    fields:
      - { name: A, bits: "3:0", access: RW, reset: 0x0 }
      - { name: B, bits: "2:1", access: RW, reset: 0x0 }
"""


class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Response:
    def __init__(self, text):
        self.content = [_Block(text)]


class FakeMessages:
    """Returns scripted responses in order; records every request."""

    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Response(self.scripted.pop(0))


class FakeClient:
    def __init__(self, scripted):
        self.messages = FakeMessages(scripted)


def test_valid_on_first_try():
    client = FakeClient([VALID_YAML])
    result = nl_to_yaml("a timer with an enable bit", client)
    assert result.attempts == 1
    assert result.spec["block"]["name"] == "timer_csr"
    assert result.error_history == []


def test_correction_loop_fixes_invalid_yaml():
    client = FakeClient([INVALID_YAML, VALID_YAML])
    result = nl_to_yaml("a timer", client)
    assert result.attempts == 2
    assert len(result.error_history) == 1
    assert "overlap" in result.error_history[0]
    # the retry request must contain the assistant's bad YAML and the errors
    second_call = client.messages.calls[1]
    roles = [m["role"] for m in second_call["messages"]]
    assert roles == ["user", "assistant", "user"]
    assert "overlap" in second_call["messages"][2]["content"]


def test_code_fences_are_stripped():
    fenced = f"```yaml\n{VALID_YAML}```"
    client = FakeClient([fenced])
    result = nl_to_yaml("a timer", client)
    assert result.attempts == 1
    assert not result.yaml_text.startswith("```")


def test_gives_up_after_retry_budget():
    client = FakeClient([INVALID_YAML] * 3)   # initial + 2 retries, all bad
    with pytest.raises(Nl2YamlError) as ei:
        nl_to_yaml("a timer", client, max_retries=2)
    assert ei.value.attempts == 3
    assert len(ei.value.error_history) == 3


def test_system_prompt_is_cached_and_stable():
    client = FakeClient([VALID_YAML])
    nl_to_yaml("a timer", client)
    system = client.messages.calls[0]["system"]
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    # deterministic assembly: identical across calls (cache-friendly)
    assert build_system_prompt() == build_system_prompt()
    # the contract rules and schema are embedded
    assert "EITHER `fields` OR register-level" in system[0]["text"]
    assert '"W1C"' in system[0]["text"]


def test_adaptive_thinking_enabled():
    client = FakeClient([VALID_YAML])
    nl_to_yaml("a timer", client)
    assert client.messages.calls[0]["thinking"] == {"type": "adaptive"}
