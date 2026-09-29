"""Music conformance must exercise the model, rather than accept its local default."""

import json
import os

import httpx
import pytest

from immich_memories.config_models_llm import LLMConfig
from immich_memories.conformance.runtime import run_case


@pytest.mark.parametrize("mood,valid", [("calm", True), ("energetic", False)])
def test_mood_probe_uses_the_saved_cut_and_restores_database_environment(monkeypatch, mood, valid):
    from immich_memories.conformance.music_cases import music_cases

    before = os.environ.get("IMMICH_MEMORIES_DATABASE_URL")
    answer = {
        "primary_mood": mood,
        "energy_level": "low",
        "tempo_suggestion": "slow",
        "genre_suggestions": ["ambient"],
        "specific_style": None,
    }
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )
    )
    # WHY: only the external provider HTTP response is substituted.
    monkeypatch.setattr(httpx.AsyncClient, "_transport_for_url", lambda *_: transport)
    result = run_case(
        music_cases(LLMConfig(model="fixture", base_url="http://localhost:43210/v1"))[0]
    )
    assert result.valid is valid
    assert result.calls == 1
    assert os.environ.get("IMMICH_MEMORIES_DATABASE_URL") == before
