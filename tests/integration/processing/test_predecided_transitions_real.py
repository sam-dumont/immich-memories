"""Asked-for fades survive a film whose clips were too short for them (#2348).

A fade between clips shorter than two fades is cut instead. That downgrade was
written into the settings' own `predecided_transitions`, so the next film assembled
with the same settings lost its fades too.
"""

from __future__ import annotations

import subprocess
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

FPS, FADE = 30, 0.5


def _clip(folder: Path, seconds: float) -> AssemblyClip:
    path = folder / f"clip_{seconds}.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=s=160x90:r={FPS}:d={seconds}",
         "-f", "lavfi", "-i", f"sine=d={seconds}", "-c:v", "libx264", "-c:a", "aac",
         "-shortest", str(path)],
        check=True,
        capture_output=True,
    )  # fmt: skip
    return AssemblyClip(path=path, duration=seconds)


def _frames(film: Path) -> int:
    video = next(s for s in ffprobe_json(film)["streams"] if s["codec_type"] == "video")
    return int(video["nb_frames"])


def test_a_second_film_keeps_the_fade_the_first_could_not_have(tmp_path):
    settings = AssemblySettings(
        encoding_plan=standalone_assembly_encoding_plan(28),
        target_resolution=(160, 90),
        transition=TransitionType.CROSSFADE,
        transition_duration=FADE,
        predecided_transitions=["fade"],
        scale_mode="fit",
    )
    assembler = VideoAssembler(settings)
    short = _clip(tmp_path, 0.6)
    assembler.assemble([short, short], tmp_path / "short.mp4")

    long = _clip(tmp_path, 2.0)
    film = assembler.assemble([long, long], tmp_path / "long.mp4")

    assert _frames(film) == round((2 * 2.0 - FADE) * FPS)
