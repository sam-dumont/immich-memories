"""Explicit image-provider routing through playback preparation."""

import json
import sqlite3
from types import SimpleNamespace

import httpx
import pytest

from immich_memories.analysis.editorial_runtime_ports import production_story_motion
from immich_memories.config_loader import Config
from immich_memories.store.editorial_preparation import initialize
from tests.conftest import make_asset


@pytest.mark.skipif(__import__("shutil").which("ffmpeg") is None, reason="needs ffmpeg")
def test_opted_in_preparation_routes_motion_to_the_llm_and_reuses_it(monkeypatch, tmp_path):
    from immich_memories.analysis.editorial_description_contract import validate_envelope
    from immich_memories.analysis.editorial_preparation import prepare_editorial_annotations
    from immich_memories.analysis.editorial_preparation_captions import _remember_caption
    from tests.test_editorial_preparation import preview
    from tests.test_playback_keyframes import encode

    config = Config(
        tier="nas",
        llm={"base_url": "http://localhost:43210/v1", "model": "fixture-vision-model"},
        editorial={"preparation": {"caption_provider": "llm"}},
    )
    asset = make_asset("clip")
    database = tmp_path / "annotations.sqlite"
    with sqlite3.connect(database) as connection:
        initialize(connection)
        _remember_caption(
            connection,
            asset.id,
            validate_envelope(
                {
                    "description": "Coloured patterns.",
                    "setting": "a screen",
                }
            ),
        )
    data = encode(tmp_path / "clip.mp4", gop=30)
    requests = []

    def reply(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert payload["model"] == config.llm.model
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"description":"The pattern moves."}'},
                    }
                ],
            },
        )

    client = httpx.AsyncClient
    # WHY: external inference is replaced with a deterministic vision response.
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(reply), **kw)
    )
    # WHY: the unused SmolVLM HTTP endpoint must never receive a request.
    monkeypatch.setattr(
        "immich_memories.analysis.editorial_preparation_motion.open_caption_url",
        lambda *_a, **_kw: pytest.fail("unused SmolVLM motion endpoint"),
    )
    kwargs = {
        "assets": [asset],
        "store_path": database,
        "thumbnail_cache": tmp_path / "previews",
        "preparation_config": config.editorial.preparation,
        "triage_config": config.triage,
        "description_model": config.editorial.description_model,
        "llm_config": config.llm,
        "head_versions": {},
        "fetch_preview": lambda _: preview(),
        "read_playback": lambda _asset, start, length: (data[start : start + length], len(data)),
    }
    first = prepare_editorial_annotations(**kwargs)
    second = prepare_editorial_annotations(**kwargs)

    assert first.complete, first.failures
    assert second.complete, second.failures
    assert len(requests) == 1
    reader = production_story_motion(
        SimpleNamespace(config=config, assets={asset.id: asset}), cache_path=database
    )
    assert reader.observe({"asset_id": asset.id, "kind": "video", "raw_seconds": 8.0}).startswith(
        "The pattern moves."
    )
