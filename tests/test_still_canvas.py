"""Stills are prepared for the film's canvas, decided once from the whole cut (#2708).

The stills pass (#2475) prepares them after the videos, from a copy of the parameters that
holds only the stills. When the film's canvas was not decided yet, that copy voted on the
stills alone, and a tie fell back to landscape: a portrait photo in a portrait film was
laid on a landscape canvas with a blur fill, then fitted again into the portrait film.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from immich_memories import generate_clips
from immich_memories.api.models import AssetType
from immich_memories.config.loader import Config
from immich_memories.generate import GenerationParams
from immich_memories.generate_photos import detect_photo_resolution
from immich_memories.processing.assembly_config import AssemblyClip
from tests.conftest import make_clip

PORTRAIT = (1080, 1920)
LANDSCAPE = (1920, 1080)


def _photo(asset_id: str, size: tuple[int, int]):
    clip = make_clip(asset_id, width=size[0], height=size[1])
    clip.asset.type = AssetType.IMAGE
    return clip


def _video_file(path: Path) -> Path:
    subprocess.run(  # noqa: S603, S607 - a fixture clip the film's rate is read from
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=36x64:r=30:d=1", str(path)],
        check=True,
    )
    return path


@pytest.mark.parametrize(
    ("video_size", "still_sizes"),
    [
        # Three portrait videos, two landscape stills: the stills alone vote landscape.
        (PORTRAIT, [LANDSCAPE, LANDSCAPE]),
        # The stills tie, which alone falls back to the configured landscape canvas.
        (PORTRAIT, [PORTRAIT, LANDSCAPE]),
        # Three landscape videos, two portrait stills: the stills alone vote portrait.
        (LANDSCAPE, [PORTRAIT, PORTRAIT]),
    ],
    ids=["stills-vote-landscape", "stills-tie", "stills-vote-portrait"],
)
def test_every_source_is_prepared_for_the_canvas_of_the_whole_cut(
    tmp_path, monkeypatch, video_size, still_sizes
) -> None:
    videos = [make_clip(f"video-{n}", width=video_size[0], height=video_size[1]) for n in range(3)]
    stills = [_photo(f"still-{n}", size) for n, size in enumerate(still_sizes)]
    clips = [stills[0], *videos, stills[1]]
    video = _video_file(tmp_path / "video.mp4")
    canvases: dict[str, tuple[int, int]] = {}

    def rendered(extraction, clip, _progress, _name, **_kwargs):
        canvases[clip.asset.id] = detect_photo_resolution(extraction.params)
        still = clip.asset.type == AssetType.IMAGE
        return AssemblyClip(path=video, duration=1.0, asset_id=clip.asset.id, is_photo=still)

    # WHY: preparing a source downloads and encodes it; the canvas each one is prepared
    # for is what is under test (the real still render is in tests/integration/photos).
    monkeypatch.setattr(generate_clips, "_rendered_clip", rendered)
    params = GenerationParams(clips=clips, output_path=tmp_path / "film.mp4", config=Config())

    generate_clips.extract_clips(params, None, tmp_path, scratch_dir=tmp_path)

    assert canvases == dict.fromkeys([clip.asset.id for clip in clips], video_size)
    # The film assembles on the same canvas its sources were prepared for.
    assert detect_photo_resolution(params) == video_size
