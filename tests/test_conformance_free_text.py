"""Parsed but semantically wrong replies must fail provider conformance."""

import json

import httpx
import pytest

from immich_memories.config_models_llm import LLMConfig
from immich_memories.conformance.free_text_cases import free_text_cases
from immich_memories.conformance.runtime import run_case


@pytest.mark.parametrize(
    "name,answer,valid,calls",
    [
        ("subject kind", {"choice": "an animal"}, True, 3),
        ("subject kind", {"choice": "a place"}, False, 3),
        ("request reading", {"who": [], "when": ["2030"], "where": [], "what": ["cats"]}, True, 3),
        ("request reading", {"who": [], "when": ["2030"], "where": [], "what": []}, False, 3),
        ("calendar dates", {"date_from": "2030-01-01", "date_to": "2030-12-31"}, True, 1),
        ("calendar dates", {"date_from": None, "date_to": None}, False, 1),
    ],
)
def test_probe_rejects_wrong_meaning(monkeypatch, name, answer, valid, calls):
    body = json.dumps(
        (
            {"reason": "synthetic answer"}
            if name not in {"request reading", "calendar dates"}
            else {}
        )
        | answer
    )
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": body}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )
    )
    # WHY: only the provider reply changes; production questions, votes and parsers stay real.
    monkeypatch.setattr(httpx.AsyncClient, "_transport_for_url", lambda *_: transport)
    checks = free_text_cases(LLMConfig(model="fixture", base_url="http://localhost:43210/v1"))
    result = run_case(next(case for case in checks if case.name == f"free-text {name}"))
    assert result.called and result.calls == calls
    assert result.tokens == 15 * calls
    assert result.valid is valid


@pytest.mark.parametrize("age,valid", [(5, True), (6, False)])
def test_age_probe_uses_calendar_arithmetic_after_the_model_reads_age(monkeypatch, age, valid):
    answer = {"is_age": True, "whose_age": "Avery Example", "age_from": age, "age_to": age}
    test_probe_rejects_wrong_meaning(monkeypatch, "age range", answer, valid, 1)


@pytest.mark.parametrize("choices,valid", [(["toy cars"], True), (["cars"], False)])
def test_exclusion_probe_requires_the_requested_exclusion(monkeypatch, choices, valid):
    test_probe_rejects_wrong_meaning(monkeypatch, "exclusions", {"choices": choices}, valid, 3)


@pytest.mark.parametrize("choices,valid", [(["velo"], True), (["jerseys"], False)])
def test_printed_word_probe_requires_the_literal_word(monkeypatch, choices, valid):
    test_probe_rejects_wrong_meaning(monkeypatch, "printed words", {"choices": choices}, valid, 3)


@pytest.mark.parametrize(
    "choice,valid",
    [
        ("away from home: only when the request says holidays, trips or travel", True),
        ("anywhere: the request does not tie the photos to a place", False),
    ],
)
def test_place_probe_requires_the_trip_scope(monkeypatch, choice, valid):
    test_probe_rejects_wrong_meaning(monkeypatch, "place scope", {"choice": choice}, valid, 3)


def test_handoff_probe_selects_the_requested_event(monkeypatch):
    def reply(request):
        prompt = json.loads(request.content)["messages"][0]["content"]
        choice = "one day" if "How long" in prompt else "A wedding ceremony"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps({"reason": "synthetic answer", "choice": choice})
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    # WHY: only the external provider is replaced; routing and votes execute normally.
    monkeypatch.setattr(
        httpx.AsyncClient, "_transport_for_url", lambda *_: httpx.MockTransport(reply)
    )
    checks = free_text_cases(LLMConfig(model="fixture", base_url="http://localhost:43210/v1"))
    result = run_case(next(case for case in checks if case.name == "free-text film handoff"))
    assert result.valid, result.quality
    assert result.calls == 6
