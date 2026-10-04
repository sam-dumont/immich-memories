"""Real-FFmpeg checks that multi-block assembly reaches its duration seam-free.

Three probe tones at different frequencies stand in for three distinct same-caption
takes. Each starts at zero and ends on a peak, so a butt splice would step; the
crossfaded fold must not.
"""

from __future__ import annotations

import re
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

from immich_memories.audio.mixer import assemble_music

# WHY: FFmpeg only — no ML model, so it is not pinned to the heavy audio_ml xdist group.
pytestmark = pytest.mark.integration

SAMPLE_RATE = 44100
TONE_SECONDS = 4.0


def _write_tone(path: Path, hz: float) -> None:
    count = int(SAMPLE_RATE * TONE_SECONDS)
    t = np.arange(count) / SAMPLE_RATE
    envelope = t / TONE_SECONDS
    signal = envelope * np.sin(2 * np.pi * (hz + 0.25 / TONE_SECONDS) * t)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes((signal * 32767).astype("<i2").tobytes())


def _samples(path: Path) -> np.ndarray:
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
            str(SAMPLE_RATE),
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32)


@pytest.fixture
def blocks(tmp_path: Path) -> list[Path]:
    paths = []
    for i, hz in enumerate((440.0, 660.0, 880.0)):
        path = tmp_path / f"block{i}.wav"
        _write_tone(path, hz)
        paths.append(path)
    return paths


def test_assembly_reaches_the_requested_duration(blocks, tmp_path: Path) -> None:
    out = assemble_music(blocks, 15.0, tmp_path / "assembled.wav")

    assert len(_samples(out)) / SAMPLE_RATE == pytest.approx(15.0, abs=0.15)


def test_assembly_seams_do_not_step(blocks, tmp_path: Path) -> None:
    out = assemble_music(blocks, 15.0, tmp_path / "assembled.wav")

    biggest_step = float(np.abs(np.diff(_samples(out))).max())

    assert biggest_step < 0.25


def test_assembly_short_target_trims_without_a_step(blocks, tmp_path: Path) -> None:
    out = assemble_music(blocks, 6.0, tmp_path / "short.wav")

    assert len(_samples(out)) / SAMPLE_RATE == pytest.approx(6.0, abs=0.15)
    assert float(np.abs(np.diff(_samples(out))).max()) < 0.25


def _write_block(path: Path, tone_hz: float, lead_silence: bool) -> None:
    """A generated block: 2s of tone and 4s of near-silence (below -50 dB).

    ACE-Step blocks often end (or, mimicked here, start) with a few seconds of
    near-silent tail. ``lead_silence`` puts that stretch first instead.
    """
    tone_count = int(SAMPLE_RATE * 2.0)
    silence_count = int(SAMPLE_RATE * 4.0)
    tone_t = np.arange(tone_count) / SAMPLE_RATE
    tone = 0.8 * np.sin(2 * np.pi * tone_hz * tone_t)
    silence_t = np.arange(silence_count) / SAMPLE_RATE
    silence = 0.0005 * np.sin(2 * np.pi * 50 * silence_t)  # ~-66 dBFS, not digital zero
    signal = np.concatenate([silence, tone] if lead_silence else [tone, silence])
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes((signal * 32767).astype("<i2").tobytes())


def _silences_in(path: Path, min_duration: float = 1.0) -> list[tuple[float, float]]:
    """Every stretch of at least ``min_duration`` seconds under -50 dB.

    WHY no -v error: silencedetect logs its findings at the "info" level, which
    that flag would suppress along with ffmpeg's own banner noise.
    """
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


def test_assembly_seams_hold_no_long_silence(tmp_path: Path) -> None:
    """A block's near-silent tail/head must not land a long quiet stretch at a seam (#1954)."""
    block_a = tmp_path / "block_trailing_silence.wav"
    _write_block(block_a, 440.0, lead_silence=False)
    block_b = tmp_path / "block_leading_silence.wav"
    _write_block(block_b, 880.0, lead_silence=True)

    out = assemble_music([block_a, block_b], 16.0, tmp_path / "assembled.wav")

    assert _silences_in(out, min_duration=1.0) == []


def _write_block_with_internal_pause(path: Path, first_hz: float, second_hz: float) -> None:
    """A block with a quiet bridge in the middle, plus the usual trailing tail.

    2s tone, 0.6s near-silent pause, 3s tone, 4s near-silent tail (9.6s total).
    A head/tail-only trim must leave the pause and the second tone intact.
    """
    first = 0.8 * np.sin(2 * np.pi * first_hz * np.arange(int(2.0 * SAMPLE_RATE)) / SAMPLE_RATE)
    pause = 0.0005 * np.sin(2 * np.pi * 50 * np.arange(int(0.6 * SAMPLE_RATE)) / SAMPLE_RATE)
    second = 0.8 * np.sin(2 * np.pi * second_hz * np.arange(int(3.0 * SAMPLE_RATE)) / SAMPLE_RATE)
    tail = 0.0005 * np.sin(2 * np.pi * 50 * np.arange(int(4.0 * SAMPLE_RATE)) / SAMPLE_RATE)
    signal = np.concatenate([first, pause, second, tail])
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes((signal * 32767).astype("<i2").tobytes())


def test_assembly_keeps_an_internal_pause_and_what_follows_it(tmp_path: Path) -> None:
    """Only the lead-in/tail get trimmed; a mid-block pause is not the tail (#1973)."""
    block = tmp_path / "block_with_pause.wav"
    _write_block_with_internal_pause(block, 440.0, 880.0)

    out = assemble_music([block], 5.8, tmp_path / "assembled.wav")

    samples = _samples(out)
    assert len(samples) / SAMPLE_RATE == pytest.approx(5.8, abs=0.1)
    # The second tone (after the pause) must survive, not be cut away with the tail.
    second_tone_window = samples[int(3.0 * SAMPLE_RATE) : int(3.3 * SAMPLE_RATE)]
    assert np.sqrt(np.mean(second_tone_window**2)) > 0.3


def _write_silent_block(path: Path, duration: float) -> None:
    """A generated block that never has audible content (below -50 dB throughout)."""
    count = int(SAMPLE_RATE * duration)
    silence = 0.0005 * np.sin(2 * np.pi * 50 * np.arange(count) / SAMPLE_RATE)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes((silence * 32767).astype("<i2").tobytes())


def test_assembly_drops_an_entirely_silent_block_instead_of_chaining_it(tmp_path: Path) -> None:
    """A fully silent block must not be kept untrimmed: that reintroduces the
    exact multi-second gap the trim exists to close (#1973)."""
    block_a = tmp_path / "block_tone.wav"
    _write_block(block_a, 440.0, lead_silence=False)
    silent_block = tmp_path / "block_silent.wav"
    _write_silent_block(silent_block, 5.0)

    out = assemble_music([block_a, silent_block], 10.0, tmp_path / "assembled.wav")

    assert _silences_in(out, min_duration=1.0) == []


def test_assembly_keeps_a_silent_block_when_every_block_is_silent(tmp_path: Path) -> None:
    """Dropping every block would leave nothing to assemble: fall back, with a warning."""
    silent_a = tmp_path / "silent_a.wav"
    _write_silent_block(silent_a, 3.0)
    silent_b = tmp_path / "silent_b.wav"
    _write_silent_block(silent_b, 3.0)

    out = assemble_music([silent_a, silent_b], 8.0, tmp_path / "assembled.wav")

    assert len(_samples(out)) / SAMPLE_RATE == pytest.approx(8.0, abs=0.15)
