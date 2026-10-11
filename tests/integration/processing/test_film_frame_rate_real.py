"""The film plays at its videos' own frame rate (#2348).

24 and 25 fps libraries were stretched to 30 with judder, only the first 20 clips
were probed, and photos, rendered at 30, counted as footage.
"""

from __future__ import annotations

import subprocess
from fractions import Fraction
from pathlib import Path

import pytest

from immich_memories.processing.assembly_config import (
    AssemblyClip,
    AssemblySettings,
    TransitionType,
    standalone_assembly_encoding_plan,
)
from immich_memories.processing.video_assembler import VideoAssembler
from tests.integration.conftest import ffprobe_json, requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]


def _clip(folder: Path, name: str, rate: int, seconds: float = 0.5) -> Path:
    path = folder / f"{name}.mp4"
    if not path.exists():
        subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
             f"testsrc2=s=160x90:r={rate}:d={seconds}", "-f", "lavfi", "-i",
             f"sine=d={seconds}", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(path)],
            check=True,
            capture_output=True,
        )  # fmt: skip
    return path


def _film_rate(clips: list[AssemblyClip], output: Path) -> Fraction:
    settings = AssemblySettings(
        encoding_plan=standalone_assembly_encoding_plan(28),
        target_resolution=(160, 90),
        transition=TransitionType.CUT,
        scale_mode="fit",
    )
    film = VideoAssembler(settings).assemble(clips, output)
    video = next(s for s in ffprobe_json(film)["streams"] if s["codec_type"] == "video")
    return Fraction(video["avg_frame_rate"])


@pytest.mark.feature("render.media-small-fixes")
@pytest.mark.parametrize("rate", [24, 25])
def test_a_film_of_24_or_25_fps_videos_and_a_photo_keeps_their_rate(tmp_path, rate):
    clips = [AssemblyClip(path=_clip(tmp_path, f"video{i}", rate), duration=0.5) for i in range(2)]
    # A photo clip is rendered at 30 fps; it takes the film's rate, not the other way round.
    clips.insert(1, AssemblyClip(path=_clip(tmp_path, "photo", 30), duration=0.5, is_photo=True))

    assert _film_rate(clips, tmp_path / "film.mp4") == rate


@pytest.mark.feature("render.media-small-fixes")
def test_a_60_fps_video_late_in_a_long_film_sets_its_rate(tmp_path):
    clips = [AssemblyClip(path=_clip(tmp_path, "video30", 30, 0.2), duration=0.2)] * 21
    clips.append(AssemblyClip(path=_clip(tmp_path, "video60", 60, 0.2), duration=0.2))

    assert _film_rate(clips, tmp_path / "film.mp4") == 60
