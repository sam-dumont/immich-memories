"""Video offload keeps the sampled-frame decision and its persistent identity."""

import base64
import json

import httpx
import pytest

from immich_memories.analysis.editorial_clip_frames import CLIP_FRAMES_HEAD, CLIP_FRAMES_VERSION
from immich_memories.config_models_inference import InferenceConfig
from tests.annotation_rows import annotation_store, read_rows
from tests.test_editorial_preparation import preview
from tests.test_editorial_preparation_motion import prepared_video
from tests.test_playback_keyframes import encode, requires_ffmpeg
from tests.test_remote_facts_preparation import ENDPOINT, answer, remote_run, transport


@requires_ffmpeg
def test_video_offloads_frames_and_preview_then_reuses_the_bank(monkeypatch, tmp_path):
    data = encode(tmp_path / "clip.mp4", gop=30)
    images = []

    def handle(request):
        payload = json.loads(request.content)
        image = base64.b64decode(payload["image"])
        images.append(image)
        body = answer(payload["producers"])
        if "nsfw_marqo" in body["producers"]:
            fact = body["producers"]["nsfw_marqo"]["facts"][0]
            held = image != preview()
            fact.update(label="yes" if held else "no", confidence=0.9 if held else 0.1)
        if "heads" in body["producers"]:
            for fact in body["producers"]["heads"]["facts"]:
                if fact["head"] == "frame_kind":
                    fact["label"] = "people_moment" if image != preview() else "nothing"
        return httpx.Response(200, json=body, headers={"X-Facts-Seconds": "0.2"})

    transport(monkeypatch, handle)

    def prepare():
        return remote_run(
            tmp_path,
            assets=[prepared_video("vv1")],
            # WHY: Immich serves the real encoded fixture through its byte-range boundary.
            read_playback=lambda _id, start, length: (data[start : start + length], len(data)),
        )

    result = prepare()
    assert result.complete and result.failures == {}
    # One preview for its ordinary heads, then the frames plus the exposure preview.
    assert 4 <= len(images) <= 10 and images.count(preview()) == 2
    row = next(r for r in read_rows(annotation_store(), "head_facts") if r["head"] == "nsfw_marqo")
    assert (row["asset_id"], row["label"], row["confidence"], row["encoder_key"]) == (
        "vv1",
        "yes",
        0.9,
        "pinned-nsfw_marqo",
    )
    frames = next(
        r for r in read_rows(annotation_store(), "head_facts") if r["head"] == CLIP_FRAMES_HEAD
    )
    assert (frames["label"], frames["confidence"], frames["version"], frames["encoder_key"]) == (
        "shows_its_moment",
        1.0,
        CLIP_FRAMES_VERSION,
        "pinned-heads",
    )
    images.clear()
    assert prepare().complete
    assert images == []


@requires_ffmpeg
@pytest.mark.parametrize("failure", ["unreachable", "changed_model"])
def test_an_incomplete_clip_banks_neither_aggregate_and_honours_no_fallback(
    monkeypatch, tmp_path, failure
):
    data = encode(tmp_path / "clip.mp4", gop=30)
    frames = 0

    def handle(request):
        nonlocal frames
        payload = json.loads(request.content)
        body = answer(payload["producers"])
        if "nsfw_marqo" in payload["producers"]:
            frames += 1
            if frames == 2:
                if failure == "unreachable":
                    return httpx.Response(503, json={"detail": "model unavailable"})
                body["producers"]["nsfw_marqo"]["encoder_key"] = "different-artifact"
        return httpx.Response(200, json=body)

    transport(monkeypatch, handle)
    result = remote_run(
        tmp_path,
        assets=[prepared_video("vv1")],
        inference=InferenceConfig(facts_base_url=ENDPOINT, fallback_to_local=False),
        # WHY: a real fixture served at the Immich playback boundary.
        read_playback=lambda _id, start, length: (data[start : start + length], len(data)),
    )
    assert not result.complete and "no local fallback" in result.failures["remote_frames"]
    assert not any(
        r["head"] in ("nsfw_marqo", CLIP_FRAMES_HEAD)
        for r in read_rows(annotation_store(), "head_facts")
    )


@requires_ffmpeg
def test_live_companion_offloads_exposure_under_its_own_id(monkeypatch, tmp_path):
    from tests.test_editorial_preparation import asset

    data = encode(tmp_path / "clip.mp4", gop=30)
    asked = []

    def handle(request):
        payload = json.loads(request.content)
        asked.append(payload["producers"])
        return httpx.Response(200, json=answer(payload["producers"]))

    transport(monkeypatch, handle)
    result = remote_run(
        tmp_path,
        assets=[asset("still").model_copy(update={"live_photo_video_id": "companion"})],
        # WHY: the companion playback endpoint; sampling remains real FFmpeg.
        read_playback=lambda _id, start, length: (data[start : start + length], len(data)),
    )
    assert result.complete and result.failures == {}
    rows = [r for r in read_rows(annotation_store(), "head_facts") if r["asset_id"] == "companion"]
    assert len(rows) == 1 and rows[0]["head"] == "nsfw_marqo"
    assert all(names == ["nsfw_marqo"] for names in asked[1:])
