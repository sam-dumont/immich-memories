"""Occasion decisions request the JSON mode their parsers require."""

import json

import httpx
import pytest

from immich_memories.analysis.special_day import ask_if_special
from immich_memories.analysis.special_day_holiday import was_the_holiday
from immich_memories.analysis.special_day_sequence import read_in_sequence
from immich_memories.config_models_llm import LLMConfig
from immich_memories.conformance.fixtures import race_assets
from immich_memories.conformance.occasion_cases import sequence
from tests.annotation_rows import annotation_store


def _model_reply(monkeypatch, answer):
    sent = []

    def respond(request):
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}]
            },
        )

    transport = httpx.MockTransport(respond)
    # WHY: only the external HTTP provider is replaced; the real producer and store run.
    monkeypatch.setattr(httpx.AsyncClient, "_transport_for_url", lambda *_: transport)
    return (
        LLMConfig(enabled=True, model="fixture", base_url="https://reader.example/v1"),
        sent,
    )


def test_sequence_requests_json_from_the_provider(monkeypatch):
    config, sent = _model_reply(
        monkeypatch, {"occasions": [{"run": "R1", "what": "a cycling race"}]}
    )
    assert sequence(config) == "finds the race and leaves the ordinary afternoon out"
    assert sent[0].get("response_format") == {"type": "json_object"}


def test_sequence_without_a_store_keeps_its_json_contract(monkeypatch):
    config, sent = _model_reply(
        monkeypatch, {"occasions": [{"run": "R1", "what": "a cycling race"}]}
    )
    assets = race_assets()
    day = assets[0].file_created_at.date()

    result = read_in_sequence(
        {day: assets},
        captions={a.id: a.llm_description for a in assets},
        llm_config=config,
        judgments=None,
    )

    assert result.found == {day: "a cycling race"}
    assert sent[0].get("response_format") == {"type": "json_object"}


@pytest.mark.parametrize("banked", [False, True])
def test_holiday_decision_requests_json_with_or_without_a_store(monkeypatch, banked):
    config, sent = _model_reply(monkeypatch, {"the_holiday": False})
    store = annotation_store() if banked else None

    assert was_the_holiday("Christmas", "Cycling race", "Cyclists racing", config, store) is False
    assert sent[0].get("response_format") == {"type": "json_object"}


@pytest.mark.parametrize("banked", [False, True])
@pytest.mark.parametrize("captioned", [False, True])
def test_day_decision_requests_json_for_both_evidence_paths(monkeypatch, banked, captioned):
    config, sent = _model_reply(
        monkeypatch,
        {
            "special": True,
            "title": "Cycling race",
            "subtitle": "",
            "what": "A cycling race",
            "window": None,
        },
    )
    assets = race_assets()
    captions = {a.id: a.llm_description for a in assets} if captioned else None

    result = ask_if_special(
        assets, config, captions=captions, judgments=annotation_store() if banked else None
    )

    assert result.judged and result.special and result.title == "Cycling race"
    assert sent[0].get("response_format") == {"type": "json_object"}
