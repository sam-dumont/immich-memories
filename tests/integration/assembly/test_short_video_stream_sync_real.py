"""Sound stays on the picture after clips whose video stream ends before their audio (#2347).

Each clip is a clapper: one white frame and a beep at the same second. Its video
stream stops 0.1 s before its audio, so the container, and the clip, is as long as
the audio. Measured in the finished film, the last clapper's flash and beep must
still land within one frame of each other.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from immich_memories.processing.assembly_config import (
    AssemblyClip,
    AssemblySettings,
    TransitionType,
    standalone_assembly_encoding_plan,
)
from immich_memories.processing.video_assembler import VideoAssembler
from tests.integration.conftest import requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]

WIDTH, HEIGHT, FPS, RATE = 160, 96, 30, 48000
CLAP, VIDEO_SECONDS, AUDIO_SECONDS, CLIPS = 1.0, 1.9, 2.0, 3


def _clapper(tmp_path: Path, index: int) -> Path:
    path = tmp_path / f"clapper_{index}.mp4"
    flash = round(CLAP * FPS)
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
            f"color=black:s={WIDTH}x{HEIGHT}:r={FPS}:d={VIDEO_SECONDS},format=gray,"
            f"geq=lum='if(eq(N\\,{flash})\\,255\\,0)',format=yuv420p",
            "-f", "lavfi", "-i",
            f"aevalsrc='if(between(t\\,{CLAP}\\,{CLAP + 0.1})\\,0.8*sin(2*PI*1000*t)\\,0)'"
            f":s={RATE}:d={AUDIO_SECONDS}",
            "-c:v", "libx264", "-crf", "10", "-c:a", "aac", str(path),
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    return path


def _flash_seconds(film: Path) -> list[float]:
    luma = np.frombuffer(
        subprocess.check_output(
            ["ffmpeg", "-v", "error", "-i", str(film), "-vf", "scale=1:1,format=gray"]
            + ["-f", "rawvideo", "-"]
        ),
        np.uint8,
    )
    return [index / FPS for index in np.flatnonzero(luma > 128)]


def _beep_onsets(film: Path) -> list[float]:
    samples = np.frombuffer(
        subprocess.check_output(
            ["ffmpeg", "-v", "error", "-i", str(film), "-map", "0:a:0", "-ac", "1"]
            + ["-ar", str(RATE), "-f", "f32le", "-"]
        ),
        "<f4",
    )
    loud = np.abs(samples) > 0.1
    rising = np.flatnonzero(loud[1:] & ~loud[:-1]) + 1
    onsets: list[float] = []
    for sample in rising:
        if not onsets or sample / RATE - onsets[-1] > 0.5:
            onsets.append(sample / RATE)
    return onsets


def test_the_last_clappers_flash_and_beep_stay_within_a_frame(tmp_path):
    settings = AssemblySettings(
        encoding_plan=standalone_assembly_encoding_plan(10),
        target_resolution=(WIDTH, HEIGHT),
        transition=TransitionType.CUT,
        scale_mode="fit",
        normalize_clip_audio=False,
    )
    clips = [
        AssemblyClip(path=_clapper(tmp_path, index), duration=AUDIO_SECONDS)
        for index in range(CLIPS)
    ]

    film = VideoAssembler(settings).assemble(clips, tmp_path / "film.mp4")

    flashes, beeps = _flash_seconds(film), _beep_onsets(film)
    assert len(flashes) == len(beeps) == CLIPS
    assert abs(flashes[-1] - beeps[-1]) < 1 / FPS, (flashes, beeps)
