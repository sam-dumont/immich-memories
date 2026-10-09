"""Preparation saves and releases one frame batch before reading the next."""

from dataclasses import replace

import pytest

from immich_memories.config_models_editorial_preparation import EditorialPreparationConfig
from tests.annotation_rows import annotation_store, read_rows
from tests.test_editorial_detector_frames import _live_photo, requires_ffmpeg
from tests.test_editorial_preparation import preview, run, successful_ports
from tests.test_editorial_preparation_motion import prepared_video
from tests.test_playback_keyframes import encode


def _bank_clip_frames(**kwargs):
    # WHY: replace the classifier weights with a completed answer, retaining real banking.
    from immich_memories.analysis.editorial_clip_frames import CLIP_FRAMES_HEAD, CLIP_FRAMES_VERSION
    from immich_memories.store.editorial_preparation import remember_head_rows

    remember_head_rows(
        kwargs["store"],
        [
            {
                "asset_id": key,
                "head": CLIP_FRAMES_HEAD,
                "version": CLIP_FRAMES_VERSION,
                "label": "shows_its_moment",
                "confidence": 1.0,
                "encoder_key": "fixture",
            }
            for key in kwargs["frame_paths"]
        ],
    )
    return {}


@requires_ffmpeg
@pytest.mark.parametrize("companions", [False, True], ids=["videos", "live-photo-clips"])
def test_frame_batches_bank_answers_and_release_files_before_the_next_read(tmp_path, companions):
    data = encode(tmp_path / "clip.mp4", gop=30)
    clip_ids = [f"clip-{i}" for i in range(5)]
    assets = [
        _live_photo(f"still-{i}", key) if companions else prepared_video(key)
        for i, key in enumerate(clip_ids)
    ]
    ports = replace(successful_ports([]), clip_frames=_bank_clip_frames)
    consumed = []
    progress = []

    def detectors(**kwargs):
        # WHY: model execution is the boundary; sampling, FFmpeg and banking are real.
        frames = kwargs["frame_paths"]
        assert len(frames) <= 2
        assert all(path.exists() for paths in frames.values() for path in paths)
        consumed.extend(path for paths in frames.values() for path in paths)
        return ports.detectors(**kwargs)

    def read(key, start, length):
        # WHY: the Immich byte-range endpoint serves a real encoded fixture.
        if key == clip_ids[2]:
            banked = {
                row["asset_id"]
                for row in read_rows(annotation_store(), "head_facts")
                if row["head"] == "nsfw_marqo"
            }
            assert set(clip_ids[:2]) <= banked
            assert consumed and not any(path.exists() for path in consumed)
        return data[start : start + length], len(data)

    result = run(
        tmp_path,
        assets=assets,
        ports=replace(ports, detectors=detectors),
        preparation_config=EditorialPreparationConfig(tier="no_captions", batch_size=2),
        fetch_preview=lambda _: preview(),
        read_playback=read,
        progress=lambda stage, done, total: progress.append((stage, done, total)),
    )

    assert result.complete
    assert result.pictures_by_stage["detector_frames"] == len(clip_ids)
    assert [(done, total) for stage, done, total in progress if stage == "detector_frames"] == [
        (done, len(clip_ids)) for done in range(1, len(clip_ids) + 1)
    ]
    assert not any(path.exists() for path in consumed)
    assert set(clip_ids) <= {
        row["asset_id"]
        for row in read_rows(annotation_store(), "head_facts")
        if row["head"] == "nsfw_marqo"
    }


@requires_ffmpeg
@pytest.mark.parametrize("companions", [False, True], ids=["videos", "live-photo-clips"])
def test_interruption_preserves_finished_batches_and_retry_only_reads_unfinished_clips(
    tmp_path, companions
):
    data = encode(tmp_path / "clip.mp4", gop=30)
    clip_ids = [f"clip-{i}" for i in range(3)]
    assets = [
        _live_photo(f"still-{i}", key) if companions else prepared_video(key)
        for i, key in enumerate(clip_ids)
    ]
    interrupted = True
    fetched = set()

    def read(key, start, length):
        # WHY: interrupt the real sampler at the Immich byte-range boundary.
        if interrupted and key == clip_ids[2]:
            raise KeyboardInterrupt
        fetched.add(key)
        return data[start : start + length], len(data)

    def prepare():
        return run(
            tmp_path,
            assets=assets,
            ports=replace(successful_ports([]), clip_frames=_bank_clip_frames),
            preparation_config=EditorialPreparationConfig(tier="no_captions", batch_size=2),
            fetch_preview=lambda _: preview(),
            read_playback=read,
        )

    with pytest.raises(KeyboardInterrupt):
        prepare()
    assert not list(tmp_path.rglob("detector-*.jpg"))
    interrupted = False
    fetched.clear()
    assert prepare().complete
    assert fetched == {clip_ids[2]}


@requires_ffmpeg
def test_remote_frame_answers_are_committed_before_sampling_the_next_batch(tmp_path, monkeypatch):
    import json

    import httpx

    from immich_memories.config_models_inference import InferenceConfig
    from tests.test_editorial_preparation import refusing_ports
    from tests.test_remote_facts_preparation import ENDPOINT, answer, transport

    data = encode(tmp_path / "clip.mp4", gop=30)
    clip_ids = [f"clip-{i}" for i in range(3)]
    # WHY: replace the inference HTTP boundary; aggregation and batch commits remain real.
    transport(
        monkeypatch,
        lambda request: httpx.Response(200, json=answer(json.loads(request.content)["producers"])),
    )

    def read(key, start, length):
        # WHY: serve an actual video from the Immich byte-range boundary.
        if key == clip_ids[2]:
            banked = {
                row["asset_id"]
                for row in read_rows(annotation_store(), "head_facts")
                if row["head"] == "nsfw_marqo"
            }
            assert set(clip_ids[:2]) <= banked
            assert not list((tmp_path / "previews").glob("immich-detector-frames-*/clip-0"))
        return data[start : start + length], len(data)

    result = run(
        tmp_path,
        assets=[_live_photo(f"still-{i}", key) for i, key in enumerate(clip_ids)],
        ports=refusing_ports("heads", "detectors", "captions")[0],
        preparation_config=EditorialPreparationConfig(tier="no_captions", batch_size=2),
        inference_config=InferenceConfig(facts_base_url=ENDPOINT, fallback_to_local=False),
        fetch_preview=lambda _: preview(),
        read_playback=read,
    )
    assert result.complete
    assert not result.failures
