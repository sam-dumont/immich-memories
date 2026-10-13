"""Real-FFmpeg checks that a long film's takes join as one piece of music (#2472).

Two synthetic takes play the same tempo with an accented downbeat each bar, but
over different sustained tones and at different loudness, standing in for two
takes of one caption. The join must keep the bar grid running across the seam,
must not hold both tones at once for more than a moment, and must not jump in level.
"""

from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

from immich_memories.audio.take_join import join_takes

# WHY: FFmpeg only — no ML model, so it is not pinned to the heavy audio_ml xdist group.
pytestmark = pytest.mark.integration

RATE = 48000
BPM = 120
BEAT = 60 / BPM
BAR = 4 * BEAT
TONE_A, TONE_B = 440.0, 311.0


def _write_take(path: Path, *, hz: float, phase: float, level: float, seconds: float) -> None:
    count = int(RATE * seconds)
    t = np.arange(count) / RATE
    signal = 0.3 * level * np.sin(2 * np.pi * hz * t)
    noise = np.random.default_rng(0).uniform(-1, 1, int(0.004 * RATE))
    beat = 0
    while (start := phase + beat * BEAT) < seconds - 0.01:
        at = int(start * RATE)
        accent = 1.0 if beat % 4 == 0 else 0.35
        end = min(at + noise.size, count)
        signal[at:end] += level * accent * noise[: end - at]
        beat += 1
    stereo = np.repeat(np.clip(signal, -1, 1)[:, None], 2, axis=1)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes((stereo * 32767).astype("<i2").tobytes())


def _mono(path: Path) -> np.ndarray:
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
    return np.frombuffer(raw, dtype=np.float32)


def _tone_levels(samples: np.ndarray, hz: float) -> np.ndarray:
    """Per-20 ms frame magnitude of one sustained tone (clicks are broadband and short)."""
    frame = int(0.1 * RATE)
    hop = int(0.02 * RATE)
    window = np.hanning(frame)
    bin_index = round(hz * frame / RATE)
    levels = []
    for start in range(0, samples.size - frame, hop):
        spectrum = np.abs(np.fft.rfft(samples[start : start + frame] * window))
        levels.append(spectrum[bin_index - 1 : bin_index + 2].max())
    return np.asarray(levels)


def _accent_times(samples: np.ndarray) -> np.ndarray:
    """Onsets of the loud bar-accent clicks."""
    edge = np.abs(np.diff(samples))
    hop = int(0.005 * RATE)
    envelope = np.array([edge[i : i + hop].max() for i in range(0, edge.size - hop, hop)])
    loud = envelope > 0.6 * envelope.max()
    onsets = np.flatnonzero(loud[1:] & ~loud[:-1]) + 1
    times = onsets * hop / RATE
    keep = [times[0]] if times.size else []
    for value in times[1:]:
        if value - keep[-1] > 0.2:
            keep.append(value)
    return np.asarray(keep)


def _two_takes(directory: Path, *, second_level: float) -> list[Path]:
    first = directory / "take0.wav"
    second = directory / "take1.wav"
    _write_take(first, hz=TONE_A, phase=0.13, level=0.4, seconds=24.0)
    _write_take(second, hz=TONE_B, phase=0.31, level=second_level, seconds=24.0)
    return [first, second]


@pytest.fixture
def takes(tmp_path: Path) -> list[Path]:
    """The second take louder, as a fresh take often is."""
    return _two_takes(tmp_path, second_level=1.0)


@pytest.fixture
def even_takes(tmp_path: Path) -> list[Path]:
    """Equal loudness, so every bar accent of both takes reads above the detector's floor."""
    return _two_takes(tmp_path, second_level=0.4)


def test_join_reaches_the_target_length(takes: list[Path], tmp_path: Path) -> None:
    out = join_takes(takes, 40.0, tmp_path / "joined.wav", bpm=BPM)

    assert _mono(out).size / RATE == pytest.approx(40.0, abs=0.05)


def test_two_takes_never_sound_together_beyond_a_short_crossfade(
    takes: list[Path], tmp_path: Path
) -> None:
    samples = _mono(join_takes(takes, 40.0, tmp_path / "joined.wav", bpm=BPM))
    a, b = _tone_levels(samples, TONE_A), _tone_levels(samples, TONE_B)
    floor = 0.05 * max(a.max(), b.max())

    both = (a > floor) & (b > floor) & (np.abs(20 * np.log10((a + 1e-9) / (b + 1e-9))) < 12)

    # Analysis frames are 100 ms wide, so a 0.3 s crossfade reads as at most ~0.4 s.
    assert both.sum() * 0.02 <= 0.5


def test_the_bar_grid_runs_on_across_the_seam(even_takes: list[Path], tmp_path: Path) -> None:
    samples = _mono(join_takes(even_takes, 40.0, tmp_path / "joined.wav", bpm=BPM))

    gaps = np.diff(_accent_times(samples))

    assert gaps.size > 10
    assert np.all(np.abs(gaps - BAR) < 0.06), gaps


def test_the_next_take_is_level_matched(takes: list[Path], tmp_path: Path) -> None:
    samples = _mono(join_takes(takes, 40.0, tmp_path / "joined.wav", bpm=BPM))
    a, b = _tone_levels(samples, TONE_A), _tone_levels(samples, TONE_B)
    seam = int(np.argmax(b > 0.5 * b.max()))
    before = a[max(seam - 150, 0) : seam - 25].mean()
    after = b[seam + 25 : seam + 150].mean()

    assert abs(20 * np.log10(after / before)) < 3.0


def test_a_film_longer_than_every_take_loops_on_the_same_grid(
    even_takes: list[Path], tmp_path: Path
) -> None:
    samples = _mono(join_takes(even_takes, 70.0, tmp_path / "looped.wav", bpm=BPM))

    gaps = np.diff(_accent_times(samples))

    assert samples.size / RATE == pytest.approx(70.0, abs=0.05)
    assert np.all(np.abs(gaps - BAR) < 0.06), gaps
