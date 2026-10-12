"""Which prepared source a later run reuses, and when it must prepare again (#2032)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from immich_memories import generate_prepared_sources
from immich_memories.analysis.editorial_planner import EditorialSelection
from immich_memories.api.models import AssetType, ExifInfo
from immich_memories.cache.prepared_source_bank import PreparedSourceBank
from immich_memories.config_loader import Config
from immich_memories.generate import GenerationParams
from immich_memories.generate_prepared_sources import (
    PreparationRequest,
    preparation_key,
    reuse_or_prepare,
)
from immich_memories.processing.assembly_config import AssemblyClip
from immich_memories.processing.encoding_plan import HdrMode
from immich_memories.processing.output_canvas import OutputCanvas
from tests.conftest import make_clip

TAKEN = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)


def _params(clip, **overrides) -> GenerationParams:
    config = Config()
    config.hardware.enabled = False
    config.tier = "basic"
    fields = {
        "clips": [clip],
        "output_path": Path("film.mp4"),
        "config": config,
        "output_canvas": OutputCanvas(1920, 1080, "landscape"),
        "clip_segments": {clip.asset.id: (1.0, 3.0)},
    }
    fields.update(overrides)
    return GenerationParams(**fields)


def _video(asset_id: str = "video-1"):
    clip = make_clip(asset_id, file_created_at=TAKEN)
    clip.asset.checksum = "sha1-of-the-original"
    return clip


def _photo(asset_id: str = "photo-1"):
    clip = _video(asset_id)
    clip.asset.type = AssetType.IMAGE
    clip.asset.original_file_name = f"{asset_id}.HEIC"
    return clip


def _request(clip, output_dir: Path, directive=None, **overrides) -> PreparationRequest:
    return PreparationRequest(_params(clip, **overrides), clip, directive, output_dir)


# Each mutation touches one input the prepared bytes depend on.
_SOURCE_CHANGES: dict[str, Callable] = {
    "checksum": lambda clip, _params: setattr(clip.asset, "checksum", "another-original"),
    "updated_at": lambda clip, _params: setattr(clip.asset, "updated_at", datetime.now(tz=UTC)),
    "modified": lambda clip, _params: setattr(clip.asset, "file_modified_at", datetime.now(tz=UTC)),
    "edited": lambda clip, _params: setattr(clip.asset, "is_edited", True),
    "file name": lambda clip, _params: setattr(clip.asset, "original_file_name", "x.MP4"),
    "live companion": lambda clip, _params: setattr(clip.asset, "live_photo_video_id", "comp-1"),
    "clip duration": lambda clip, _params: setattr(clip, "duration_seconds", 9.0),
    "trim window": lambda clip, params: params.clip_segments.update({clip.asset.id: (1.0, 3.5)}),
    "tier": lambda _clip, params: setattr(params.config, "tier", "full"),
    "codec": lambda _clip, params: setattr(params.config.output, "codec", "h265"),
    "hdr mode": lambda _clip, params: setattr(params.config.output, "hdr_mode", HdrMode.SDR),
    "resolution": lambda _clip, params: setattr(params.config.output, "resolution", "720p"),
    "quality": lambda _clip, params: setattr(params.config.output, "crf", 30),
    "hardware": lambda _clip, params: setattr(params.config.hardware, "enabled", True),
    "encoder preset": lambda _clip, params: setattr(params.config.hardware, "encoder_preset", "x"),
    "local file": lambda clip, _params: setattr(clip, "local_path", "/elsewhere/video.MOV"),
    "burst": lambda clip, _params: (
        setattr(clip, "live_burst_video_ids", ["a", "b"]),
        setattr(clip, "live_burst_trim_points", [(0.0, 1.0), (0.0, 1.0)]),
    ),
    "certified live": lambda clip, _params: setattr(clip, "editorial_live_manifest", {"v": 1}),
}

_RENDER_CHANGES: dict[str, Callable] = {
    "canvas": lambda _clip, params: setattr(
        params, "output_canvas", OutputCanvas(1280, 720, "landscape")
    ),
    "photo duration": lambda _clip, params: setattr(params.config.photos, "duration", 7.0),
    "output format": lambda _clip, params: setattr(params, "output_format", "mov"),
    "scale mode": lambda _clip, params: setattr(params, "scale_mode", "fit"),
    "faces": lambda clip, _params: setattr(clip.asset, "people", [{"id": "p1", "name": ""}]),
    "place": lambda clip, _params: setattr(clip.asset, "exif_info", ExifInfo(city="Elsewhere")),
}


def _key_after(change: Callable, clip_factory, tmp_path: Path, directive=None) -> tuple[str, str]:
    before = _request(clip_factory(), tmp_path, directive)
    clip = clip_factory()
    params = _params(clip)
    change(clip, params)
    after = PreparationRequest(params, clip, directive, tmp_path)
    return preparation_key(before), preparation_key(after)


@pytest.mark.parametrize("change", list(_SOURCE_CHANGES.values()), ids=list(_SOURCE_CHANGES))
def test_every_source_and_recipe_input_changes_a_videos_key(change, tmp_path):
    before, after = _key_after(change, _video, tmp_path)
    assert before != after


@pytest.mark.parametrize(
    "change",
    list(_RENDER_CHANGES.values()) + [_SOURCE_CHANGES["tier"]],
    ids=[*_RENDER_CHANGES, "tier"],
)
def test_every_render_input_changes_a_photos_key(change, tmp_path):
    before, after = _key_after(change, _photo, tmp_path)
    assert before != after


@pytest.mark.parametrize(
    "directive",
    [
        EditorialSelection("video-1", 1.0, 3.0, render_mode="motion"),
        EditorialSelection("video-1", 1.0, 3.0, render_mode="still", render_frame_seconds=2.0),
        EditorialSelection("video-1", 1.0, 3.0, render_mode="still", render_frame_seconds=2.5),
    ],
    ids=["motion", "still", "another frame"],
)
def test_the_render_directive_changes_the_key(directive, tmp_path):
    assert preparation_key(_request(_video(), tmp_path)) != preparation_key(
        _request(_video(), tmp_path, directive)
    )


def test_a_new_recipe_version_retires_every_entry(tmp_path, monkeypatch):
    before = preparation_key(_request(_video(), tmp_path))
    monkeypatch.setattr(generate_prepared_sources, "RECIPE_VERSION", "prepared-source-v999")
    assert preparation_key(_request(_video(), tmp_path)) != before


def test_a_new_app_version_retires_every_entry(tmp_path, monkeypatch):
    before = preparation_key(_request(_video(), tmp_path))
    monkeypatch.setattr(generate_prepared_sources, "__version__", "99.0.0")
    assert preparation_key(_request(_video(), tmp_path)) != before


def test_labels_that_never_reach_the_bytes_keep_a_videos_key(tmp_path):
    clip = _video()
    clip.llm_emotion = "joyful"
    clip.asset.is_favorite = True
    clip.asset.exif_info = ExifInfo(city="Elsewhere")
    params = _params(clip, clip_rotations={clip.asset.id: 90})
    # A video's canvas, faces and place are applied at assembly, not baked into its segment.
    params.output_canvas = OutputCanvas(1080, 1920, "portrait")

    assert preparation_key(PreparationRequest(params, clip, None, tmp_path)) == preparation_key(
        _request(_video(), tmp_path)
    )


class _Preparer:
    """Stands in for the run's preparation: writes a file where the run would."""

    def __init__(self, output_dir: Path, payload: bytes = b"prepared") -> None:
        self.output_dir = output_dir
        self.payload = payload
        self.calls = 0
        self._lock = threading.Lock()

    def photo(self) -> AssemblyClip:
        with self._lock:
            self.calls += 1
        path = self.output_dir / "photos" / "photo-1_photo.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.payload)
        return AssemblyClip(
            path=path,
            duration=4.0,
            asset_id="photo-1",
            is_photo=True,
            gain_map_hdr=True,
            location_name="Somewhere",
        )

    def segment(self) -> AssemblyClip:
        with self._lock:
            self.calls += 1
        path = self.output_dir / ".live_segments" / f"seg-{threading.get_ident()}.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.payload)
        return AssemblyClip(path=path, duration=1.96, asset_id="video-1")


def _dress(rotation: int | None) -> Callable[[Path, float], AssemblyClip]:
    return lambda path, duration: AssemblyClip(
        path=path, duration=duration, asset_id="video-1", rotation_override=rotation
    )


def test_a_second_render_reuses_the_photo_it_prepared(tmp_path):
    bank = PreparedSourceBank(tmp_path / "bank", max_bytes=10**9)
    first = _Preparer(tmp_path / "run1")
    second = _Preparer(tmp_path / "run2")

    fresh = reuse_or_prepare(
        bank, _request(_photo(), first.output_dir), prepare=first.photo, dress=_dress(None)
    )
    reused = reuse_or_prepare(
        bank, _request(_photo(), second.output_dir), prepare=second.photo, dress=_dress(None)
    )

    assert (first.calls, second.calls) == (1, 0)
    assert reused is not None and fresh is not None
    # The reused clip lands in the second run's folder, where its own render would have.
    assert reused.path == second.output_dir / "photos" / "photo-1_photo.mp4"
    assert reused.path.read_bytes() == b"prepared"
    assert (reused.duration, reused.is_photo, reused.gain_map_hdr, reused.location_name) == (
        4.0,
        True,
        True,
        "Somewhere",
    )


def test_a_reused_segment_takes_this_runs_labels(tmp_path):
    bank = PreparedSourceBank(tmp_path / "bank", max_bytes=10**9)
    first = _Preparer(tmp_path / "run1")
    reuse_or_prepare(
        bank, _request(_video(), first.output_dir), prepare=first.segment, dress=_dress(None)
    )

    second = _Preparer(tmp_path / "run2")
    reused = reuse_or_prepare(
        bank, _request(_video(), second.output_dir), prepare=second.segment, dress=_dress(270)
    )

    assert second.calls == 0
    assert reused is not None
    assert (reused.duration, reused.rotation_override) == (1.96, 270)
    assert reused.path.parent == second.output_dir / ".live_segments"


def test_a_changed_source_is_prepared_again(tmp_path):
    bank = PreparedSourceBank(tmp_path / "bank", max_bytes=10**9)
    first = _Preparer(tmp_path / "run1")
    reuse_or_prepare(
        bank, _request(_photo(), first.output_dir), prepare=first.photo, dress=_dress(None)
    )
    replaced = _photo()
    replaced.asset.checksum = "the-owner-replaced-the-file"
    second = _Preparer(tmp_path / "run2", payload=b"new bytes")

    result = reuse_or_prepare(
        bank, _request(replaced, second.output_dir), prepare=second.photo, dress=_dress(None)
    )

    assert second.calls == 1
    assert result is not None and result.path.read_bytes() == b"new bytes"


def test_a_damaged_entry_is_prepared_again(tmp_path):
    bank = PreparedSourceBank(tmp_path / "bank", max_bytes=10**9)
    first = _Preparer(tmp_path / "run1", payload=b"p" * 4096)
    reuse_or_prepare(
        bank, _request(_photo(), first.output_dir), prepare=first.photo, dress=_dress(None)
    )
    for media in (tmp_path / "bank").rglob("*.mp4"):
        media.write_bytes(b"q" * 4096)  # same size, other bytes: a bad disk, a stray write
    second = _Preparer(tmp_path / "run2", payload=b"p" * 4096)

    result = reuse_or_prepare(
        bank, _request(_photo(), second.output_dir), prepare=second.photo, dress=_dress(None)
    )

    assert second.calls == 1
    assert result is not None and result.path.read_bytes() == b"p" * 4096


def test_two_preparers_of_one_source_both_finish_and_the_bank_holds_one(tmp_path):
    bank = PreparedSourceBank(tmp_path / "bank", max_bytes=10**9)
    start = threading.Barrier(2)
    results: list[AssemblyClip | None] = []

    def run(name: str) -> None:
        preparer = _Preparer(tmp_path / name)

        def prepare() -> AssemblyClip:
            start.wait()  # both miss before either banks
            return preparer.segment()

        results.append(
            reuse_or_prepare(
                bank, _request(_video(), preparer.output_dir), prepare=prepare, dress=_dress(None)
            )
        )

    threads = [threading.Thread(target=run, args=(name,)) for name in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert all(result is not None and result.path.is_file() for result in results)
    later = _Preparer(tmp_path / "later")
    reused = reuse_or_prepare(
        bank, _request(_video(), later.output_dir), prepare=later.segment, dress=_dress(None)
    )
    assert later.calls == 0
    assert reused is not None and reused.path.read_bytes() == b"prepared"


def test_a_file_outside_the_run_and_scratch_is_not_banked(tmp_path):
    bank = PreparedSourceBank(tmp_path / "bank", max_bytes=10**9)
    stray = tmp_path / "elsewhere" / "clip.mp4"
    stray.parent.mkdir()
    stray.write_bytes(b"bytes")

    reuse_or_prepare(
        bank,
        _request(_video(), tmp_path / "run"),
        prepare=lambda: AssemblyClip(path=stray, duration=1.0),
        dress=_dress(None),
    )

    assert bank.kept == 0


def test_a_source_without_a_checksum_is_never_banked(tmp_path):
    bank = PreparedSourceBank(tmp_path / "bank", max_bytes=10**9)
    clip = _photo()
    clip.asset.checksum = None
    first = _Preparer(tmp_path / "run1")
    second = _Preparer(tmp_path / "run2")

    reuse_or_prepare(
        bank, _request(clip, first.output_dir), prepare=first.photo, dress=_dress(None)
    )
    reuse_or_prepare(
        bank, _request(clip, second.output_dir), prepare=second.photo, dress=_dress(None)
    )

    assert (first.calls, second.calls, bank.kept) == (1, 1, 0)
