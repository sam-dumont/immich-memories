"""An explicit image-caption choice never silently borrows an unconfigured reader."""

import io
import json

import httpx
import pytest
from PIL import Image

from immich_memories.analysis.editorial_preparation import prepare_editorial_annotations
from immich_memories.analysis.llm_metrics import collecting
from immich_memories.analysis.prepared_captions import prepared_captions
from immich_memories.api.models import AssetType
from immich_memories.config_loader import Config
from immich_memories.config_tiers import nas_draft_config
from immich_memories.preflight import CheckStatus, check_caption_endpoint
from tests.conftest import make_asset

LLM = {"base_url": "http://localhost:43210/v1", "model": "fixture-vision-model"}


def test_llm_caption_opt_in_requires_a_configured_llm():
    with pytest.raises(ValueError, match="caption_provider.*configured LLM"):
        Config(tier="nas", editorial={"preparation": {"caption_provider": "llm"}})


def test_configuring_a_text_llm_never_opts_nas_into_image_requests(monkeypatch, tmp_path):
    from tests.test_editorial_preparation import preview

    config = Config(tier="nas", llm=LLM)
    # WHY: any request to the configured model would cross an unapproved image boundary.
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **_kw: pytest.fail("LLM requested without caption opt-in")
    )

    result = prepare_editorial_annotations(
        assets=[make_asset("one").model_copy(update={"type": AssetType.IMAGE, "duration": None})],
        store_path=tmp_path / "annotations.sqlite",
        thumbnail_cache=tmp_path / "previews",
        preparation_config=config.editorial.preparation,
        triage_config=config.triage,
        head_versions={},
        llm_config=config.llm,
        fetch_preview=lambda _: preview(),
    )

    assert result.complete
    assert "captions" not in result.pictures_by_stage
    assert "motion" not in result.pictures_by_stage


def test_opted_in_nas_captions_wait_for_refinement_and_warn_about_cost(caplog, tmp_path):
    config = Config(tier="nas", llm=LLM, editorial={"preparation": {"caption_provider": "llm"}})
    path = tmp_path / "config.yaml"
    config.save_yaml(path)
    reloaded = Config.from_yaml(path)

    assert reloaded.editorial.preparation.demands_captions
    assert reloaded.tier == "nas"
    assert reloaded.editorial.reader == "rules"
    assert not reloaded.editorial.laya_audience
    assert not nas_draft_config(reloaded).editorial.preparation.demands_captions
    assert "less efficient" in caplog.text.lower()
    assert "expensive" in caplog.text.lower()
    assert "hosted" in caplog.text.lower()


@pytest.mark.parametrize("valid_reply", [True, False])
def test_opted_in_acquisition_uses_the_llm_once_then_reuses_its_caption(
    monkeypatch, tmp_path, valid_reply
):
    requests = []

    def reply(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert str(request.url) == LLM["base_url"] + "/chat/completions"
        assert payload["model"] == LLM["model"]
        assert payload["messages"][0]["content"][1]["type"] == "image_url"
        return httpx.Response(
            200,
            json={
                "model": "fixture-served-revision",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {"description": "A cat sleeps.", "setting": "a room"}
                                if valid_reply
                                else {"wrong": "schema"}
                            )
                        },
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 12},
            },
        )

    client = httpx.AsyncClient
    # WHY: the configured model is an external HTTP boundary; no test sends real images to it.
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(reply), **kw)
    )
    database = tmp_path / "annotations.sqlite"
    config = Config(
        tier="nas",
        llm=LLM,
        editorial={
            "annotation_database": str(database),
            "preparation": {"caption_provider": "llm"},
        },
    )
    image = io.BytesIO()
    Image.new("RGB", (80, 60), (123, 83, 66)).save(image, "JPEG")
    kwargs = {
        "assets": [
            make_asset("new").model_copy(update={"type": AssetType.IMAGE, "duration": None})
        ],
        "store_path": database,
        "thumbnail_cache": tmp_path / "previews",
        "preparation_config": config.editorial.preparation,
        "triage_config": config.triage,
        "description_model": config.editorial.description_model,
        "head_versions": {},
        "llm_config": config.llm,
        "fetch_preview": lambda _: image.getvalue(),
        "fetch_faces": lambda _: [],
    }
    with collecting() as usage:
        first = prepare_editorial_annotations(**kwargs)
        second = prepare_editorial_annotations(**kwargs)

    if not valid_reply:
        assert not first.complete and not second.complete
        assert "configured LLM" in second.failures["captions"]
        assert "caption_base_url" not in second.failures["captions"]
        assert prepared_captions(config, ("new",)) == {}
        assert len(requests) == 2  # A failed synthetic control leaves the picture uncaptioned.
        return
    assert first.complete, first.failures
    assert second.complete, second.failures
    assert len(requests) == 4  # Three synthetic schema controls, then the one missing picture.
    assert usage.by_stage["caption_controls"].calls == 3
    assert usage.by_stage["caption"].calls == 1
    assert usage.preparation_calls == 4
    assert prepared_captions(config, ("new",)) == {"new": "A cat sleeps."}
    assert first.caption_provenance["origins"][0]["model_id"] == LLM["model"]


def test_preflight_names_the_opted_in_llm_cost_and_never_probes_smolvlm(monkeypatch):
    # WHY: preflight must not contact an unused external caption service.
    monkeypatch.setattr(httpx, "get", lambda *_a, **_kw: pytest.fail("SmolVLM inventory queried"))
    config = Config(tier="nas", llm=LLM, editorial={"preparation": {"caption_provider": "llm"}})

    result = check_caption_endpoint(config)

    assert result.status is CheckStatus.WARNING
    assert LLM["model"] in result.message
    assert "less efficient" in result.details
    assert "expensive" in result.details
    assert "hosted" in result.details
