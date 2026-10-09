"""Ducking follows the visible music clip after many fractional-frame trims."""

import subprocess
from pathlib import Path

import numpy as np
import pytest

from immich_memories.audio.mixer import (
    DuckingConfig,
    MixConfig,
    mix_audio_with_ducking,
    music_mute_windows,
)
from immich_memories.processing.assembly_config import (
    AssemblyClip,
    AssemblySettings,
    standalone_assembly_encoding_plan,
)
from immich_memories.processing.streaming_assembler import streaming_assemble_full
from immich_memories.processing.video_assembler import VideoAssembler
from tests.integration.conftest import requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]


def _ffmpeg(*args: str) -> bytes:
    return subprocess.run(
        ["ffmpeg", "-v", "error", "-y", *args], check=True, capture_output=True, timeout=60
    ).stdout


def _source(path: Path, color: str, fps: float) -> None:
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"color={color}:s=32x32:r={fps}:d=1.1",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=48000:cl=stereo:d=1.1",
        "-c:v",
        "ffv1",
        "-c:a",
        "pcm_s16le",
        str(path),
    )


def _visible_red_window(path: Path, fps: float) -> tuple[float, float]:
    pixels = np.frombuffer(
        _ffmpeg(
            "-i", str(path), "-an", "-vf", "scale=1:1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"
        ),
        dtype=np.uint8,
    ).reshape(-1, 3)
    red = np.flatnonzero(pixels[:, 0] > 3)
    assert red.size
    return red[0] / fps, (red[-1] + 1) / fps


def _audible_duck_window(path: Path) -> tuple[float, float]:
    samples = np.frombuffer(
        _ffmpeg("-i", str(path), "-vn", "-ac", "1", "-ar", "48000", "-f", "f32le", "-"),
        dtype=np.float32,
    )
    # Five-ms RMS windows ignore sine zero crossings and retain the audible edge.
    blocks = samples[: samples.size // 240 * 240].reshape(-1, 240)
    rms = np.sqrt(np.mean(blocks**2, axis=1))
    quiet = np.flatnonzero(rms < np.median(rms) * 0.2)
    quiet = quiet[(quiet > 20) & (quiet < len(rms) - 20)]
    assert quiet.size
    # Ignore any separately padded tail: the clip's continuous duck is the longest dip.
    regions = np.split(quiet, np.flatnonzero(np.diff(quiet) > 1) + 1)
    window = max(regions, key=len)
    return window[0] * 0.005, (window[-1] + 1) * 0.005


@pytest.mark.parametrize(
    "fps, engine, duration, fade",
    [(fps, False, 1.029, 0.5) for fps in (24, 25, 29.97, 30, 60)]
    + [
        (30, True, 1.029, 0.5),
        (60, True, 1.029, 0.5),
        (30, True, 0.629, 0.5),
        (30, True, 1.029, 0.01),
    ],
    ids=[
        "stream-24",
        "stream-25",
        "stream-29.97",
        "stream-30",
        "stream-60",
        "engine-30",
        "engine-60",
        "engine-short",
        "engine-zero-frame",
    ],
)
def test_soundtrack_mute_tracks_the_visible_clip(tmp_path, fps, engine, duration, fade):
    blue, red = tmp_path / "blue.mkv", tmp_path / "red.mkv"
    _source(blue, "blue", fps)
    _source(red, "red", fps)
    clips = [AssemblyClip(blue, duration) for _ in range(20)]
    clips.extend([AssemblyClip(red, duration, has_music=True), AssemblyClip(blue, duration)])
    film = tmp_path / "film.mp4"
    plan = standalone_assembly_encoding_plan(18)
    if engine:
        settings = AssemblySettings(
            encoding_plan=plan,
            target_resolution=(32, 32),
            normalize_clip_audio=False,
            transition_duration=fade,
        )
        VideoAssembler(settings).assemble(clips, film)
        windows = settings.music_mute_windows
    else:
        transitions = ["fade"] * (len(clips) - 1)
        streaming_assemble_full(
            clips,
            transitions,
            film,
            32,
            32,
            fps,
            fade_duration=fade,
            encoding_plan=plan,
            normalize_audio=False,
        )
        windows = music_mute_windows(clips, transitions, fade, fps=fps)
    music = tmp_path / "music.wav"
    _ffmpeg("-f", "lavfi", "-i", "sine=f=1000:r=48000:d=30", str(music))
    mixed = mix_audio_with_ducking(
        film,
        music,
        tmp_path / "mixed.mp4",
        config=MixConfig(
            ducking=DuckingConfig(),
            fade_in_seconds=0,
            fade_out_seconds=0,
            normalize_audio=False,
            mute_windows=windows,
        ),
    )
    visible_start, visible_end = _visible_red_window(mixed, fps)
    quiet_start, quiet_end = _audible_duck_window(mixed)
    print(
        f"fps={fps} engine={engine} visible={visible_start, visible_end} ducked={quiet_start, quiet_end}"
    )
    # A dissolve's last frame is already all-blue; hard cuts expose the full last frame.
    end = visible_end + (1 / fps if fade * fps >= 1 and duration >= 2 * fade else 0)
    # WAV decodes in 4096-sample blocks, when FFmpeg evaluates volume's enable.
    # Allow that fixed block plus the RMS resolution; it never grows with clip count.
    assert quiet_start == pytest.approx(visible_start, abs=4096 / 48000 + 0.005)
    assert quiet_end == pytest.approx(end, abs=4096 / 48000 + 0.005)
    assert windows == [pytest.approx((visible_start, end), abs=1e-6)]
