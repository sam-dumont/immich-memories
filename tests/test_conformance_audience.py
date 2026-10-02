"""Audience probes validate private-activity and exposure judgments separately."""

import json

import httpx
import pytest

from immich_memories.config_models_llm import LLMConfig
from immich_memories.conformance.runtime import run_case


@pytest.mark.parametrize("name,calls", [("audience activity", 1), ("audience exposure", 2)])
def test_audience_probe_keeps_the_expected_privacy_hold(monkeypatch, name, calls):
    from immich_memories.conformance.audience_cases import audience_cases

    def reply(request):
        prompt = json.loads(request.content)["messages"][0]["content"]
        if '"observations"' in prompt:
            body = {"observations": {"p1": [["a person", "clothing"]]}}
        else:
            body = {
                "finding": "toileting_or_changing" if name.endswith("activity") else "none",
                "why": "Visible activity.",
            }
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(body)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    # WHY: only external provider replies are fixed; evidence and privacy floors are production code.
    monkeypatch.setattr(
        httpx.AsyncClient, "_transport_for_url", lambda *_: httpx.MockTransport(reply)
    )
    checks = audience_cases(
        LLMConfig(enabled=True, model="fixture", base_url="http://localhost:43210/v1")
    )
    result = run_case(next(case for case in checks if case.name == name))
    assert result.valid, result.quality
    assert result.calls == calls
