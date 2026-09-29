"""Both episode prompt contracts must return a grounded, bankable reading."""

import json

import httpx
import pytest

from immich_memories.config_models_llm import LLMConfig
from immich_memories.conformance.runtime import run_case


@pytest.mark.parametrize("name", ["episode reading", "lean episode reading"])
def test_episode_probe_uses_full_membership_and_reads_the_subject(monkeypatch, name):
    from immich_memories.conformance.episode_cases import episode_cases

    body = {
        "schema_version": "episode-reading-text-v1",
        "episodes": [
            {
                "episode": 1,
                "what_happened": "A chess tournament.",
                "representatives": [{"asset": 1, "reason": "Chessboards show the tournament"}],
                "cull": [],
                "notable_moments": [],
            }
        ],
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
    # WHY: the external provider is replaced; episode grouping and persistence run normally.
    monkeypatch.setattr(httpx.AsyncClient, "_transport_for_url", lambda *_: transport)
    checks = episode_cases(LLMConfig(model="fixture", base_url="http://localhost:43210/v1"))
    result = run_case(next(case for case in checks if case.name == name))
    assert result.valid, result.quality
    assert result.calls == 1
