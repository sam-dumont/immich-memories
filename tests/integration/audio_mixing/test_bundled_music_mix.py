"""Real-FFmpeg check that a long bundled-music film loops cleanly and plays at full level.

#2070: without ACE-Step (every Docker/NAS install), the bundled mix landed at -29 to
-35 dBFS against generated music's -21 to -24 — the bundled branch's final
amix defaulted to ``normalize=1``, scaling the sum down to avoid clipping,
while the 4-stem (generated-music) path already used ``normalize=0`` plus the
shared true-peak limiter. This loops one bundled track over a 5+ minute film and checks it
against the generated-music path on the same source material.
"""

from __future__ import annotations

import re
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

from immich_memories.audio.mixer import (
    DuckingConfig,
    MixConfig,
    mix_audio_with_ducking,
)
from immich_memories.audio.mixer_helpers import mix_audio_with_4stem_ducking
from immich_memories.audio.take_join import loop_track

pytestmark = pytest.mark.integration

RATE = 44100
TRACK_SECONDS = 25.0
FILM_SECONDS = 320.0  # 5+ minutes: far longer than any single bundled track.
# The AAC round trip's own overshoot, same bound test_true_peak_headroom.py uses.
CEILING = 10 ** (-1.0 / 20)


def _write_tone(path: Path, frequency: float, amplitude: float, duration: float) -> None:
    time = np.arange(int(duration * RATE)) / RATE
    signal = amplitude * np.sin(2 * np.pi * frequency * time)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(RATE)
        stream.writeframes((signal * 32767).astype("<i2").tobytes())


def _bundled_track(tmp_path: Path) -> Path:
    """One "calm" bundled track, far shorter than the film."""
    track = tmp_path / "calm.wav"
    _write_tone(track, 220.0, amplitude=0.6, duration=TRACK_SECONDS)
    return track


def _make_video(path: Path, duration: float) -> None:
    """A black video with a quiet-but-not-digital-zero audio track."""
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=black:s=32x32:r=5:d={duration}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=100:duration={duration}:sample_rate={RATE}",
            "-af",
            "volume=0.02",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
    )


def _decoded_peak(path: Path) -> float:
    raw = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-f",
            "f32le",
            "-ac",
            "1",
            "-ar",
            str(RATE),
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    samples = np.frombuffer(raw, dtype=np.float32)
    assert samples.size, "decoded output has no samples"
    return float(np.abs(samples).max())


def _integrated_loudness(path: Path) -> float:
    report = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(path), "-af", "ebur128", "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=True,
    ).stderr
    match = re.search(r"Integrated loudness:\s*\n\s*I:\s*(-?[\d.]+) LUFS", report)
    assert match, f"no integrated loudness reported:\n{report}"
    return float(match.group(1))


def _silences_in(path: Path, min_duration: float = 0.5) -> list[tuple[float, float]]:
    report = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af",
            f"silencedetect=noise=-50dB:d={min_duration}",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stderr
    starts = [float(m) for m in re.findall(r"silence_start: ([\d.]+)", report)]
    ends = [float(m) for m in re.findall(r"silence_end: ([\d.]+)", report)]
    return list(zip(starts, ends, strict=False))


@pytest.fixture(scope="module")
def _bundled_looped_track(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The mastered bundled track, looped over a 5+ minute film."""
    tmp_path = tmp_path_factory.mktemp("bundled_mix")
    looped = loop_track(_bundled_track(tmp_path), FILM_SECONDS, tmp_path / "bundled_looped.wav")

    from immich_memories.audio.mastering import master_music_track

    return master_music_track(looped, tmp_path / "mastered_bundled.wav")


def test_the_loop_has_no_long_silence_at_its_seams(_bundled_looped_track: Path) -> None:
    assert _silences_in(_bundled_looped_track, min_duration=0.5) == []


def test_the_bundled_mix_stays_under_the_true_peak_ceiling(
    tmp_path: Path, _bundled_looped_track: Path
) -> None:
    video = tmp_path / "video.mp4"
    _make_video(video, FILM_SECONDS)

    output = mix_audio_with_ducking(video, _bundled_looped_track, tmp_path / "bundled_mixed.mp4")

    assert _decoded_peak(output) <= CEILING


def test_the_bundled_mix_matches_the_generated_music_mixs_loudness(
    tmp_path: Path, _bundled_looped_track: Path
) -> None:
    """Same source, same ducking config, through each path: loudness must agree.

    This is the stem-mix target the issue asks the bundled path to meet: not a
    hardcoded LUFS number, but the level ``mix_audio_with_4stem_ducking`` (the
    generated-music path) already produces for the same material. The other
    three "stems" are silent — a bundled track is never actually separated —
    so both paths carry the same one music signal and only the amix/ducking
    machinery around it differs.
    """
    video = tmp_path / "video.mp4"
    _make_video(video, FILM_SECONDS)
    silent_stem = tmp_path / "silent_stem.wav"
    _write_tone(silent_stem, frequency=0.0, amplitude=0.0, duration=FILM_SECONDS)

    bundled_output = mix_audio_with_ducking(
        video,
        _bundled_looped_track,
        tmp_path / "bundled_mixed.mp4",
        config=MixConfig(ducking=DuckingConfig()),
    )
    stem_output = mix_audio_with_4stem_ducking(
        video,
        _bundled_looped_track,
        silent_stem,
        silent_stem,
        silent_stem,
        tmp_path / "stem_mixed.mp4",
        config=MixConfig(ducking=DuckingConfig()),
    )

    bundled_loudness = _integrated_loudness(bundled_output)
    stem_loudness = _integrated_loudness(stem_output)

    assert abs(bundled_loudness - stem_loudness) <= 1.0
