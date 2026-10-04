"""Real-FFmpeg check that every final mix stays under a true-peak ceiling.

#1954: a FULL-tier film's 4-stem mix decoded at +1.73 dBFS. The amix sums five
streams raw (normalize=0, so it can clip) and the old alimiter only capped
*sample* peaks at 0.95 (-0.45 dBFS) before AAC encoding, which overshoots on
reconstruction. Each hot-signal fixture below forces that sum past clipping,
so only a true-peak-safe limiter ahead of the encoder keeps the ENCODED
output under -1 dBFS once ffmpeg decodes it back to float.
"""

from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

from immich_memories.audio.mixer import (
    DuckingConfig,
    MixConfig,
    final_mix_safety_filter,
    mix_audio_with_ducking,
)
from immich_memories.audio.mixer_helpers import (
    StemDuckingLevels,
    mix_audio_with_4stem_ducking,
    mix_audio_with_stem_ducking,
)

pytestmark = pytest.mark.integration

RATE = 44100
CEILING = 10 ** (-1.0 / 20)  # -1 dBFS as a linear sample magnitude


def _write_tone(path: Path, frequency: float, amplitude: float, duration: float) -> None:
    time = np.arange(int(duration * RATE)) / RATE
    signal = amplitude * np.sin(2 * np.pi * frequency * time)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(RATE)
        stream.writeframes((signal * 32767).astype("<i2").tobytes())


def _write_silence(path: Path, duration: float) -> None:
    _write_tone(path, frequency=0.0, amplitude=0.0, duration=duration)


def _make_video(path: Path, audio_path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=black:s=32x32:r=10:d=6",
            "-i",
            str(audio_path),
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


def _decoded_sample_rate(path: Path) -> int:
    rate = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=sample_rate",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    return int(rate)


def test_4stem_mix_decodes_under_the_true_peak_ceiling(tmp_path: Path) -> None:
    silent_video_audio = tmp_path / "silent.wav"
    _write_silence(silent_video_audio, 6.0)
    video = tmp_path / "video.mp4"
    _make_video(video, silent_video_audio)

    stems = []
    for frequency in (80, 220, 440, 880):
        stem = tmp_path / f"stem-{frequency}.wav"
        _write_tone(stem, frequency, amplitude=0.9, duration=6.0)
        stems.append(stem)

    output = mix_audio_with_4stem_ducking(
        video,
        *stems,
        tmp_path / "mixed.mp4",
        config=MixConfig(
            ducking=DuckingConfig(music_volume_db=0.0),
            normalize_audio=False,
            fade_in_seconds=0,
            fade_out_seconds=0,
        ),
        ducking_levels=StemDuckingLevels(drums_db=0.0, bass_db=0.0, vocals_db=0.0, other_db=0.0),
    )

    assert _decoded_peak(output) <= CEILING
    # The safety filter oversamples to 192 kHz internally; the encoder must still get 48 kHz.
    assert _decoded_sample_rate(output) == 48000


def test_basic_ducking_mix_decodes_under_the_true_peak_ceiling(tmp_path: Path) -> None:
    video_audio = tmp_path / "video_audio.wav"
    _write_tone(video_audio, 300, amplitude=0.95, duration=6.0)
    video = tmp_path / "video.mp4"
    _make_video(video, video_audio)

    music = tmp_path / "music.wav"
    _write_tone(music, 500, amplitude=0.95, duration=6.0)

    output = mix_audio_with_ducking(
        video,
        music,
        tmp_path / "mixed.mp4",
        config=MixConfig(
            ducking=DuckingConfig(music_volume_db=0.0, threshold=0.9),
            normalize_audio=False,
            fade_in_seconds=0,
            fade_out_seconds=0,
        ),
    )

    assert _decoded_peak(output) <= CEILING
    assert _decoded_sample_rate(output) == 48000


def test_3stem_ducking_mix_decodes_under_the_true_peak_ceiling(tmp_path: Path) -> None:
    video_audio = tmp_path / "video_audio.wav"
    _write_tone(video_audio, 300, amplitude=0.95, duration=6.0)
    video = tmp_path / "video.mp4"
    _make_video(video, video_audio)

    accompaniment = tmp_path / "accompaniment.wav"
    _write_tone(accompaniment, 150, amplitude=0.95, duration=6.0)
    vocals = tmp_path / "vocals.wav"
    _write_tone(vocals, 600, amplitude=0.95, duration=6.0)

    output = mix_audio_with_stem_ducking(
        video,
        vocals,
        accompaniment,
        tmp_path / "mixed.mp4",
        config=MixConfig(
            ducking=DuckingConfig(music_volume_db=0.0, threshold=0.9),
            normalize_audio=False,
            fade_in_seconds=0,
            fade_out_seconds=0,
        ),
        duck_vocals_db=0.0,
    )

    assert _decoded_peak(output) <= CEILING
    assert _decoded_sample_rate(output) == 48000


def test_safety_filter_leaves_normal_level_material_unchanged(tmp_path: Path) -> None:
    """Material already under the ceiling must pass through flat, not pumped.

    -12 dBFS sits well below the -2 dBFS limiter ceiling, so the limiter
    should never engage; its attack/release defaults must not visibly move
    a peak that was never near the threshold.
    """
    source = tmp_path / "quiet.wav"
    amplitude = 10 ** (-12.0 / 20)
    _write_tone(source, 440, amplitude=amplitude, duration=3.0)

    filtered = tmp_path / "filtered.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(source),
            "-af",
            final_mix_safety_filter(),
            str(filtered),
        ],
        check=True,
    )

    before = _decoded_peak(source)
    after = _decoded_peak(filtered)
    db_change = 20 * np.log10(after / before)
    assert abs(db_change) <= 0.1
