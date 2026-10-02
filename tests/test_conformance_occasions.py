"""Occasion probes reject syntactically valid but incorrect provider decisions."""

import json

import httpx
import pytest

from immich_memories.config_models_llm import LLMConfig
from immich_memories.conformance.runtime import run_case


@pytest.mark.parametrize("the_holiday,valid", [(False, True), (True, False)])
def test_holiday_probe_checks_the_event_not_just_the_date(monkeypatch, the_holiday, valid):
    from immich_memories.conformance.occasion_cases import occasion_cases

    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps({"the_holiday": the_holiday})},
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )
    )
    # WHY: the external provider response is the only substituted boundary.
    monkeypatch.setattr(httpx.AsyncClient, "_transport_for_url", lambda *_: transport)
    checks = occasion_cases(
        LLMConfig(enabled=True, model="fixture", base_url="http://localhost:43210/v1")
    )
    result = run_case(next(case for case in checks if case.name == "holiday distinction"))
    assert result.valid is valid
    assert result.calls == 1


@pytest.mark.parametrize("name", ["captioned occasion", "recorded occasion"])
def test_day_probe_requires_a_grounded_race_verdict(monkeypatch, name):
    from immich_memories.conformance.occasion_cases import occasion_cases

    body = {
        "special": True,
        "title": "Cycling race",
        "subtitle": "",
        "what": "A cycling race",
        "window": None,
    }
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(body)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )
    )
    # WHY: provider HTTP only; evidence and the temporary judgment store are real.
    monkeypatch.setattr(httpx.AsyncClient, "_transport_for_url", lambda *_: transport)
    checks = occasion_cases(
        LLMConfig(enabled=True, model="fixture", base_url="http://localhost:43210/v1")
    )
    result = run_case(next(case for case in checks if case.name == name))
    assert result.valid, result.quality
    assert result.calls == 1


@pytest.mark.parametrize("run,valid", [("R1", True), ("R2", False)])
def test_sequence_probe_distinguishes_race_from_ordinary_day(monkeypatch, run, valid):
    from immich_memories.conformance.occasion_cases import occasion_cases

    body = {"occasions": [{"run": run, "what": "a cycling race"}]}
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(body)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )
    )
    # WHY: only the external LLM response is controlled.
    monkeypatch.setattr(httpx.AsyncClient, "_transport_for_url", lambda *_: transport)
    checks = occasion_cases(
        LLMConfig(enabled=True, model="fixture", base_url="http://localhost:43210/v1")
    )
    result = run_case(next(case for case in checks if case.name == "occasion sequence"))
    assert result.valid is valid
    assert result.calls == 1
