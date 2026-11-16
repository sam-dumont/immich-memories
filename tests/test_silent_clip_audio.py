"""A clip with no audio stream plays as silence; it never fails the film's audio (#2945).

A phone can record video with no audio track. The audio mix used to hand that file to FFmpeg as
an audio source, which ends in "Output file does not contain any stream", and the whole render
was lost at its last step.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from immich_memories.processing.assembly_config import AssemblyClip
from immich_memories.processing.probe_cache import ProbeCache
from immich_memories.processing.streaming_audio import extract_and_mix_audio

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs FFmpeg")

FPS = 30
SECONDS = 2.0


def _clip(path: Path, *, with_audio: bool) -> Path:
    command = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=size=160x120:rate={FPS}:d={SECONDS}"]
    if with_audio:
        command += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={SECONDS}", "-c:a", "aac"]
    command += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", str(path)]
    subprocess.run(command, capture_output=True, timeout=60, check=True)  # noqa: S603, S607
    return path


def _seconds(path: Path) -> float:
    result = subprocess.run(  # noqa: S603, S607
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return float(result.stdout.strip())


def _peak(path: Path, start: float, length: float) -> float:
    """Loudest sample in a stretch of the mix, in dBFS (very negative when silent)."""
    result = subprocess.run(  # noqa: S603, S607
        [
            "ffmpeg",
            "-v",
            "info",
            "-ss",
            str(start),
            "-t",
            str(length),
            "-i",
            str(path),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    line = next(row for row in result.stderr.splitlines() if "max_volume" in row)
    return float(line.split("max_volume:")[1].split("dB")[0])


@pytest.fixture
def clips(tmp_path: Path) -> tuple[Path, Path]:
    return (
        _clip(tmp_path / "with_sound.mp4", with_audio=True),
        _clip(tmp_path / "no_sound.mov", with_audio=False),
    )


def test_a_clip_without_an_audio_stream_plays_as_silence_in_the_mix(tmp_path, clips) -> None:
    with_sound, no_sound = clips
    out = tmp_path / "mix.m4a"

    extract_and_mix_audio(
        clips=[
            AssemblyClip(path=with_sound, duration=SECONDS),
            AssemblyClip(path=no_sound, duration=SECONDS),
        ],
        transitions=["cut"],
        output_path=out,
        fps=FPS,
        probe_cache=ProbeCache(),
    )

    assert _seconds(out) == pytest.approx(2 * SECONDS, abs=0.1)
    assert _peak(out, 0.2, 1.0) > -30  # the tone of the clip that has sound
    assert _peak(out, SECONDS + 0.4, 1.0) < -60  # the silent clip's stretch


def test_a_film_of_one_clip_without_an_audio_stream_gets_a_silent_track(tmp_path, clips) -> None:
    _, no_sound = clips
    out = tmp_path / "single.m4a"

    extract_and_mix_audio(
        clips=[AssemblyClip(path=no_sound, duration=SECONDS)],
        transitions=[],
        output_path=out,
        fps=FPS,
    )

    assert _seconds(out) == pytest.approx(SECONDS, abs=0.1)


def test_privacy_mode_skips_a_clip_without_an_audio_stream(tmp_path, clips) -> None:
    with_sound, no_sound = clips
    out = tmp_path / "private.m4a"

    extract_and_mix_audio(
        clips=[
            AssemblyClip(path=no_sound, duration=SECONDS),
            AssemblyClip(path=with_sound, duration=SECONDS),
        ],
        transitions=["cut"],
        output_path=out,
        fps=FPS,
        privacy_mode=True,
    )

    assert _seconds(out) == pytest.approx(2 * SECONDS, abs=0.1)
