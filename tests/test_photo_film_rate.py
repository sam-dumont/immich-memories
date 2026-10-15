"""A still moves at the film's own frame rate (#2475).

Stills used to animate at a fixed 30 fps. A film whose videos are 24 or 25 fps plays at that
rate (#2348), so each photo clip was resampled and lost one frame in five or six: the move
stepped evenly, then jumped twice as far. The film's rate is decided by its videos, so they
are prepared first and the stills follow at their rate.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from immich_memories import generate_clips, generate_photos
from immich_memories.api.models import AssetType
from immich_memories.config.loader import Config
from immich_memories.generate import GenerationParams
from immich_memories.processing.assembly_config import AssemblyClip
from tests.conftest import make_clip


def _photo(asset_id: str):
    clip = make_clip(asset_id)
    clip.asset.type = AssetType.IMAGE
    return clip


def _params(clips, tmp_path: Path, **overrides) -> GenerationParams:
    return GenerationParams(
        clips=clips, output_path=tmp_path / "film.mp4", config=Config(), **overrides
    )


def _video_file(path: Path, fps: int) -> Path:
    subprocess.run(  # noqa: S603, S607 - a fixture clip at a known rate
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=s=64x36:r={fps}:d=1",
            str(path),
        ],
        check=True,
    )
    return path


def test_a_photo_animates_at_the_rate_it_is_given(tmp_path, monkeypatch) -> None:
    seen: dict[str, int] = {}

    def render(*_args, fps: int = 30, **_kwargs):
        seen["fps"] = fps

    # WHY: the frame stream itself is covered by the photo pipeline's tests; this pins the
    # rate the film hands it.
    monkeypatch.setattr("immich_memories.photos.photo_pipeline.render_single_photo", render)
    clip = _photo("still")
    source = tmp_path / "still.jpg"
    source.write_bytes(b"")

    generate_photos.render_photo_as_clip(
        clip, _params([clip], tmp_path, photo_fps=25), tmp_path, source_path=source
    )

    assert seen == {"fps": 25}


@pytest.mark.parametrize(("video_fps", "film_fps"), [(25, 25), (24, 24), (30, 30), (60, 60)])
def test_stills_are_prepared_after_the_videos_at_their_rate(
    tmp_path, monkeypatch, video_fps: int, film_fps: int
) -> None:
    clips = [_photo("still-1"), make_clip("video"), _photo("still-2")]
    video = _video_file(tmp_path / "video.mp4", video_fps)
    prepared: list[tuple[str, int | None]] = []

    def rendered(extraction, clip, _progress, _name, **_kwargs):
        prepared.append((clip.asset.id, extraction.params.photo_fps))
        still = clip.asset.type == AssetType.IMAGE
        return AssemblyClip(path=video, duration=1.0, asset_id=clip.asset.id, is_photo=still)

    # WHY: preparing a source downloads and encodes it; the order and the rate it is
    # prepared at are what is under test.
    monkeypatch.setattr(generate_clips, "_rendered_clip", rendered)

    film = generate_clips.extract_clips(
        _params(clips, tmp_path), None, tmp_path, scratch_dir=tmp_path
    )

    assert prepared == [("video", None), ("still-1", film_fps), ("still-2", film_fps)]
    assert [clip.asset_id for clip in film] == ["still-1", "video", "still-2"]


def test_a_film_of_stills_only_moves_them_at_thirty(tmp_path, monkeypatch) -> None:
    clips = [_photo("still-1"), _photo("still-2")]
    rates: list[int | None] = []

    def rendered(extraction, clip, _progress, _name, **_kwargs):
        rates.append(extraction.params.photo_fps)
        return AssemblyClip(path=tmp_path / f"{clip.asset.id}.mp4", duration=1.0, is_photo=True)

    # WHY: as above, the rate a still is prepared at is under test, not the encode.
    monkeypatch.setattr(generate_clips, "_rendered_clip", rendered)

    generate_clips.extract_clips(_params(clips, tmp_path), None, tmp_path, scratch_dir=tmp_path)

    assert rates == [30, 30]
