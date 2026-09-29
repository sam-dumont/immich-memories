"""Catalogue probes require usable month and year accounts from production code."""

import json

import httpx

from immich_memories.config_models_llm import LLMConfig
from immich_memories.conformance.runtime import run_case


def test_catalogue_probe_reads_each_month_and_the_year(monkeypatch):
    from immich_memories.conformance.catalogue_cases import catalogue_cases

    def reply(request):
        prompt = json.loads(request.content)["messages"][0]["content"]
        keys = (
            prompt.split("Return an account for EACH of these exact keys: ")[1]
            .split(".\n")[0]
            .split(",")
        )
        body = {"accounts": {key.strip(): "Chess tournament and sailing trip." for key in keys}}
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(body)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    # WHY: only the external model HTTP boundary is replaced; both overview levels are built.
    monkeypatch.setattr(
        httpx.AsyncClient, "_transport_for_url", lambda *_: httpx.MockTransport(reply)
    )
    result = run_case(
        catalogue_cases(LLMConfig(model="fixture", base_url="http://localhost:43210/v1"))[0]
    )
    assert result.valid, result.quality
    assert result.calls == 3
