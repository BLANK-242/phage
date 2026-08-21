"""Unit tests for _tailor_one()'s hardened refusal path (build brief Task 4,
item 10). No live API calls — a fake Gemini client only.
"""

from __future__ import annotations

import pytest

from phage.vaccinator.engine import MutationRefused, _tailor_one

_NO_PARAPHRASE_JSON = '{"injection_text": "adapted text", "paraphrase": ""}'
_REFUSAL_TEXT = "I cannot help with that request."
_FULL_JSON = '{"injection_text": "adapted text v2", "paraphrase": "a structurally different reframe"}'


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text


class _FakeModels:
    def __init__(self, texts: list[str]):
        self._texts = texts
        self.calls = 0

    def generate_content(self, *, model, contents, config):
        text = self._texts[self.calls]
        self.calls += 1
        return _FakeResponse(text)


class _FakeGeminiClient:
    def __init__(self, texts: list[str]):
        self.models = _FakeModels(texts)


def test_tailor_one_raises_mutation_refused_after_three_refusals():
    client = _FakeGeminiClient([_REFUSAL_TEXT, _NO_PARAPHRASE_JSON, _REFUSAL_TEXT])

    with pytest.raises(MutationRefused) as excinfo:
        _tailor_one(
            client,
            model="fake-model",
            tool_scope=["send_email(to, subject, body)"],
            arch_id="instruction-override",
            text="template text",
            target="SUPPLIER-RELAY",
        )

    err = excinfo.value
    assert err.target == "SUPPLIER-RELAY"
    assert err.archetype_id == "instruction-override"
    assert err.attempts == 3
    assert client.models.calls == 3  # exactly 3 attempts, not more, not fewer


def test_tailor_one_succeeds_when_second_attempt_returns_paraphrase():
    client = _FakeGeminiClient([_NO_PARAPHRASE_JSON, _FULL_JSON])

    injection_text, paraphrase = _tailor_one(
        client,
        model="fake-model",
        tool_scope=["send_email(to, subject, body)"],
        arch_id="instruction-override",
        text="template text",
        target="SUPPLIER-RELAY",
    )

    assert injection_text == "adapted text v2"
    assert paraphrase == "a structurally different reframe"
    assert client.models.calls == 2  # stopped retrying once successful — third call never made
