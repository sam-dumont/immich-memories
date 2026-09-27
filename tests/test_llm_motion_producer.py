"""Motion providers reuse existing captions without confusing their bank identities."""

import json
import sqlite3
from contextlib import nullcontext
from types import SimpleNamespace

import httpx
import pytest

from immich_memories.analysis.editorial_preparation_motion import (
    MOTION_PRODUCER,
    BankedMotionLines,
    missing_motion,
    motion_sources,
    prepare_motion_lines,
    seat_asker,
)
from immich_memories.analysis.editorial_runtime_ports import production_story_motion
from immich_memories.analysis.llm_caption_identity import LLM_CAPTION_PREFIX
from immich_memories.analysis.llm_metrics import collecting
from immich_memories.config_loader import Config
from immich_memories.config_models_llm import LLMConfig
from immich_memories.store.editorial_preparation import initialize
from tests.test_editorial_preparation_motion import frame, sampled, video


def test_explicit_motion_producer_reuses_smolvlm_without_overwriting_its_bank(tmp_path):
    model = LLM_CAPTION_PREFIX + "fixture-vision-model"
    config = Config(tier="gpu", editorial={"description_model": model})
    assets = {name: video(name) for name in ("old", "new")}
    sources = motion_sources(tuple(assets.values()), residual_of=lambda _: None)
    database = tmp_path / "annotations.sqlite"
    reader = production_story_motion(
        SimpleNamespace(config=config, assets=assets), cache_path=database
    )
    assert reader.producer != MOTION_PRODUCER
    with sqlite3.connect(database) as connection:
        initialize(connection)
        common = {
            "connection": connection,
            # WHY: synthetic frames stand in for the external Immich playback boundary.
            "sample": sampled,
            "concurrency": 1,
            "check_cancelled": lambda: None,
            "progress": lambda *_: None,
        }
        # WHY: fixed completions replace external inference while exercising the real writer.
        prepare_motion_lines(
            **common, sources=sources[:1], ask=lambda _: '{"description":"A child runs."}'
        )
        pending = missing_motion(connection, sources, producer=reader.producer)
        assert [s.asset_id for s in pending] == ["new"]
        result = prepare_motion_lines(
            **common,
            sources=pending,
            ask=lambda _: '{"description":"A dog jumps."}',
            producer=reader.producer,
        )
        assert result.described == 1
        assert missing_motion(connection, sources, producer=reader.producer) == ()

    for asset, text in (("old", "A child runs."), ("new", "A dog jumps.")):
        assert reader.observe({"asset_id": asset, "kind": "video", "raw_seconds": 8.0}).startswith(
            text
        )
    default = BankedMotionLines(store_path=database, assets=assets, described=True)
    assert "A dog jumps." not in default.observe(
        {"asset_id": "new", "kind": "video", "raw_seconds": 8.0}
    )


@pytest.mark.parametrize("status", [200, 401, 403])
def test_explicit_motion_transport_uses_the_llm_and_preserves_auth_errors(monkeypatch, status):
    llm = LLMConfig(base_url="http://localhost:43210/v1", model="fixture-vision-model")
    requests = []

    def reply(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert str(request.url) == llm.base_url + "/chat/completions"
        assert payload["model"] == llm.model
        assert payload["messages"][0]["content"][1]["type"] == "image_url"
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "Credential rejected"}})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"description":"A dog jumps."}'},
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 12},
            },
        )

    client = httpx.AsyncClient
    # WHY: the model is an external HTTP boundary; only a synthetic image is sent to the stub.
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(reply), **kw)
    )
    ask = seat_asker("http://unused-smolvlm.invalid", api_key="", timeout=1, llm_config=llm)
    expected = (
        pytest.raises(PermissionError, match=rf"HTTP {status}.*llm.api_key")
        if status != 200
        else nullcontext()
    )
    with collecting() as usage, expected:
        assert json.loads(ask(frame(100))) == {"description": "A dog jumps."}
    assert len(requests) == 1
    assert usage.by_stage["motion"].calls == 1
    assert usage.preparation_calls == 1
    assert usage.unmetered_calls == (status != 200)
