"""Banking the obstruction head is add-only: a preview it cannot read keeps its old line.

It reads the tokens of the encoder call the public heads already pay for, never its own.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from immich_memories.analysis.facts.obstruction import OBSTRUCTED_LABEL
from immich_memories.analysis.preparation.heads import (
    PUBLIC_HEAD_VERSIONS,
    prepare_clip_frames,
    prepare_heads,
)
from immich_memories.analysis.preparation.obstruction_bank import OBSTRUCTION_FRAME_PRODUCER
from immich_memories.store.cut_measurements import banked_motion_residuals
from immich_memories.triage.heads import PatchHeadBundle
from tests.annotation_rows import annotation_store, read_rows
from tests.test_editorial_preparation_heads import bundle_at

TOKEN_DIM = 4
PACK_DIM = 6 * 384


class FakeEncoder:
    # WHY: the DINOv2 ONNX export is an 88 MB download no test environment holds; the
    # tokens it would produce are replaced here, everything that reads them is real.
    key = "a" * 64

    def __init__(self) -> None:
        self.calls: list[int] = []

    def embed_with_patches(self, batch: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        n = len(batch)
        self.calls.append(n)
        return np.zeros((n, PACK_DIM), np.float32), np.zeros((n, 256, TOKEN_DIM), np.float32)


def _bundle(tmp_path, *, flagged: bool):
    # Tokens are all zero in these tests, so only the intercept decides the probability.
    bundle = PatchHeadBundle(
        encoder_key="a" * 64,
        name="obstruction",
        version="public-obstruction-v1",
        mu=np.zeros(TOKEN_DIM),
        sd=np.ones(TOKEN_DIM),
        w=np.zeros(TOKEN_DIM),
        b=10.0 if flagged else -10.0,
    )
    path = tmp_path / "obstruction.npz"
    bundle.save(path)
    return path


def _jpeg(path):
    Image.new("RGB", (32, 24), (210, 140, 90)).save(path)
    return path


def _prepare(tmp_path, bundle_path, *, public=(), obstruction=("one",), encoder=None, **kwargs):
    encoder_path = tmp_path / "encoder.onnx"
    encoder_path.write_bytes(b"")
    encoder = encoder or FakeEncoder()
    return prepare_heads(
        asset_ids=list(public),
        store=annotation_store(),
        bundle_path=bundle_at(tmp_path / "heads.npz", PUBLIC_HEAD_VERSIONS),
        encoder_path=encoder_path,
        head_versions=PUBLIC_HEAD_VERSIONS,
        preview_for=kwargs.pop(
            "preview_for", lambda _asset_id: _jpeg(tmp_path / "preview.jpg").read_bytes()
        ),
        batch_size=kwargs.pop("batch_size", 8),
        check_cancelled=lambda: None,
        progress=lambda *_args: None,
        obstruction_ids=list(obstruction),
        obstruction_bundle_path=bundle_path,
        open_encoder=lambda _path, **_kwargs: encoder,
        **kwargs,
    )


def test_a_confidently_flagged_patch_map_banks_obstructed(tmp_path):
    failures = _prepare(tmp_path, _bundle(tmp_path, flagged=True))

    assert failures == {}
    rows = read_rows(annotation_store(), "head_facts")
    assert [(r["asset_id"], r["head"], r["label"]) for r in rows] == [
        ("one", "obstruction", OBSTRUCTED_LABEL)
    ]


def test_a_preview_that_cannot_be_read_is_reported_and_leaves_no_fact(tmp_path):
    failures = _prepare(
        tmp_path,
        _bundle(tmp_path, flagged=True),
        obstruction=["unreadable"],
        preview_for=lambda _asset_id: (_ for _ in ()).throw(OSError("gone")),
    )

    assert "obstruction:unreadable" in failures
    assert read_rows(annotation_store(), "head_facts") == []


def test_a_bundle_trained_on_another_encoder_is_named_and_spares_the_public_heads(tmp_path):
    bundle_path = tmp_path / "obstruction.npz"
    PatchHeadBundle(
        encoder_key="b" * 64,
        name="obstruction",
        version="public-obstruction-v1",
        mu=np.zeros(TOKEN_DIM),
        sd=np.ones(TOKEN_DIM),
        w=np.zeros(TOKEN_DIM),
        b=0.0,
    ).save(bundle_path)

    failures = _prepare(tmp_path, bundle_path, public=["one"])

    assert "another encoder" in failures["obstruction"]
    heads = {row["head"] for row in read_rows(annotation_store(), "head_facts")}
    assert heads == set(PUBLIC_HEAD_VERSIONS)


def test_every_head_reads_one_encoder_call_per_picture(tmp_path):
    encoder = FakeEncoder()
    pictures = [f"p{index}" for index in range(5)]

    failures = _prepare(
        tmp_path,
        _bundle(tmp_path, flagged=False),
        public=pictures[:4],
        obstruction=pictures[1:],
        encoder=encoder,
        batch_size=2,
    )

    assert failures == {}
    # Five pictures owe one head or both: five encoded, in batches of two, once each.
    assert encoder.calls == [2, 2, 1]
    rows = read_rows(annotation_store(), "head_facts")
    obstruction = sorted(r["asset_id"] for r in rows if r["head"] == "obstruction")
    public = sorted({r["asset_id"] for r in rows if r["head"] == "activity"})
    assert obstruction == pictures[1:] and public == pictures[:4]


def test_a_banked_picture_is_not_encoded_again(tmp_path):
    bundle_path = _bundle(tmp_path, flagged=False)
    _prepare(tmp_path, bundle_path, public=["one"], obstruction=["one"])
    encoder = FakeEncoder()

    _prepare(tmp_path, bundle_path, public=["one"], obstruction=["one"], encoder=encoder)

    assert encoder.calls == []


def _video(asset_id: str, *, duration: float = 8.0):
    from datetime import UTC, datetime

    from immich_memories.api.models import Asset

    timestamp = datetime(2024, 1, 2, tzinfo=UTC)
    return Asset(
        id=asset_id,
        type="VIDEO",
        file_created_at=timestamp,
        file_modified_at=timestamp,
        updated_at=timestamp,
        original_file_name="clip.mp4",
        width=640,
        height=480,
        duration_seconds=duration,
    )


def test_a_videos_flagged_frames_bank_as_seconds_on_its_own_producer(tmp_path):
    bundle_path = _bundle(tmp_path, flagged=True)
    encoder_path = tmp_path / "encoder.onnx"
    encoder_path.write_bytes(b"")
    frames = [_jpeg(tmp_path / f"frame-{i}.jpg") for i in range(3)]

    progress = []

    def publish(stage, done, total):
        progress.append((stage, done, total))
        if done:
            assert read_rows(annotation_store(), "motion_residuals")

    def open_encoder(_path, **_kwargs):
        assert progress == [("obstruction_frames", 0, 1)]
        return FakeEncoder()

    failures = prepare_clip_frames(
        store=annotation_store(),
        videos={"vid": _video("vid", duration=8.0)},
        frame_paths={},
        obstruction={"vid": frames},
        bundle_path=tmp_path / "unused-heads.npz",
        obstruction_bundle_path=bundle_path,
        encoder_path=encoder_path,
        check_cancelled=lambda: None,
        open_encoder=open_encoder,
        progress=publish,
    )

    assert failures == {}
    assert progress == [("obstruction_frames", 0, 1), ("obstruction_frames", 1, 1)]
    store = annotation_store()
    from immich_memories.analysis.clips.bound_sample import source_metadata_digest

    banked = banked_motion_residuals(
        store,
        {"vid": source_metadata_digest(_video("vid", duration=8.0))},
        OBSTRUCTION_FRAME_PRODUCER,
    )
    assert len(banked["vid"]["obstructed_at"]) == 3


def test_a_video_with_no_flagged_frames_banks_an_empty_list(tmp_path):
    bundle_path = _bundle(tmp_path, flagged=False)
    encoder_path = tmp_path / "encoder.onnx"
    encoder_path.write_bytes(b"")
    frames = [_jpeg(tmp_path / f"clear-{i}.jpg") for i in range(2)]

    failures = prepare_clip_frames(
        store=annotation_store(),
        videos={"vid": _video("vid")},
        frame_paths={},
        obstruction={"vid": frames},
        bundle_path=tmp_path / "unused-heads.npz",
        obstruction_bundle_path=bundle_path,
        encoder_path=encoder_path,
        check_cancelled=lambda: None,
        open_encoder=lambda _path, **_kwargs: FakeEncoder(),
    )

    assert failures == {}
    store = annotation_store()
    from immich_memories.analysis.clips.bound_sample import source_metadata_digest

    banked = banked_motion_residuals(
        store, {"vid": source_metadata_digest(_video("vid"))}, OBSTRUCTION_FRAME_PRODUCER
    )
    assert banked["vid"]["obstructed_at"] == []


def test_an_unreadable_frame_is_reported_and_leaves_no_fact(tmp_path):
    bundle_path = _bundle(tmp_path, flagged=True)
    encoder_path = tmp_path / "encoder.onnx"
    encoder_path.write_bytes(b"")

    failures = prepare_clip_frames(
        store=annotation_store(),
        videos={"vid": _video("vid")},
        frame_paths={},
        obstruction={"vid": [tmp_path / "absent.jpg"]},
        bundle_path=tmp_path / "unused-heads.npz",
        obstruction_bundle_path=bundle_path,
        encoder_path=encoder_path,
        check_cancelled=lambda: None,
        open_encoder=lambda _path, **_kwargs: FakeEncoder(),
    )

    assert "obstruction_frames:vid" in failures
