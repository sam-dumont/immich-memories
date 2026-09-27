"""Explicit image producers own their caption bank and request accounting."""

import json
import sqlite3
from contextlib import nullcontext

import httpx
import pytest

from immich_memories.analysis.editorial_preparation_captions import prepare_captions
from immich_memories.analysis.llm_caption_identity import llm_caption_identity
from immich_memories.analysis.llm_metrics import collecting
from immich_memories.analysis.prepared_captions import prepared_captions
from immich_memories.config_loader import Config
from immich_memories.config_models_llm import LLMConfig
from immich_memories.store.editorial_preparation import initialize
from tests.test_editorial_preparation import preview


@pytest.mark.parametrize("status", [200, 401, 403])
def test_explicit_llm_writer_owns_its_caption_identity_and_accounts_for_image_requests(
    monkeypatch, tmp_path, status
):
    requests = []
    llm = LLMConfig(base_url="http://localhost:43210/v1", model="fixture-vision-model")

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
                        "message": {
                            "content": '{"description":"A cat sleeps.","setting":"a room"}'
                        },
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 12},
            },
        )

    client = httpx.AsyncClient
    # WHY: synthetic tiles exercise the configured HTTP boundary without a real model call.
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(reply), **kw)
    )
    database = tmp_path / "annotations.sqlite"
    outcome = (
        pytest.raises(PermissionError, match=rf"HTTP {status}.*llm.api_key")
        if status != 200
        else nullcontext()
    )
    with sqlite3.connect(database) as connection, collecting() as usage:
        initialize(connection)
        with outcome:
            failures = prepare_captions(
                connection=connection,
                asset_ids=("one",),
                preview_for=lambda _: preview(),
                base_url="http://unused-smolvlm.invalid",
                timeout=1,
                concurrency=1,
                check_cancelled=lambda: None,
                progress=lambda *_: None,
                llm_config=llm,
            )

    if status != 200:
        assert len(requests) == 1
        return

    config = Config(
        tier="nas",
        editorial={
            "annotation_database": str(database),
            "description_model": llm_caption_identity(llm),
        },
    )
    assert not failures
    assert len(requests) == 4
    assert usage.by_stage["caption_controls"].calls == 3
    assert usage.by_stage["caption"].calls == 1
    assert usage.preparation_calls == 4
    assert prepared_captions(config, ("one",)) == {"one": "A cat sleeps."}
    smol = Config(tier="nas", editorial={"annotation_database": str(database)})
    assert prepared_captions(smol, ("one",)) == {}
