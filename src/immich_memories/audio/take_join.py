"""Join one film's generated takes into one piece of music (#2472).

A long film's soundtrack is several takes of one caption, BPM and key. They used
to be folded with a two-second blind crossfade at whatever sample a take ended
on, so two phrases, and when the takes disagreed two songs, played at once at
every seam. Here each take is cut on a bar line: the outgoing take ends on a
downbeat before its outro, the next starts on its own downbeat, and the two meet
in a short equal-power crossfade centred on that shared bar line, the next take
matched to the level of the one before. The bar grid then runs straight on
across the seam, and only a fraction of a beat ever has both takes sounding.

Beat tracking is numpy over an ffmpeg decode, like ``track_tempo``: librosa is not
a dependency of this project. The tempo is the one the takes were asked for,
refined within a few percent against the audio; with none, it is measured.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from itertools import cycle
from pathlib import Path

import numpy as np

from immich_memories.audio.track_tempo import detect_bpm

logger = logging.getLogger(__name__)

RATE = 48000
_HOP = 512
_BEATS_PER_BAR = 4
# Long enough to hide the splice, short enough that the takes never play together.
_CROSSFADE_SECONDS = 0.3
# A take's last seconds are its outro or fade; the join cuts before them.
_TAIL_GUARD_SECONDS = 4.0
_LEVEL_WINDOW_SECONDS = 6.0
_MAX_GAIN_DB = 6.0
_SILENCE = 10 ** (-45 / 20)
_FALLBACK_BPM = 120.0
_FADE_OUT_SECONDS = 2.0


@dataclass(frozen=True)
class _Take:
    """One decoded take and the stretch of it, on its bar lines, that the film uses."""

    audio: np.ndarray  # (samples, 2) float32
    start: int
    end: int


def join_takes(
    take_paths: list[Path],
    target_duration: float,
    output_path: Path,
    *,
    bpm: float | None = None,
) -> Path:
    """Write ``target_duration`` seconds of the takes, joined on bar lines, to ``output_path``.

    The takes repeat in order when the film is longer than all of them, each
    repeat joined the same way. Output is PCM WAV for mastering and ducking.
    """
    takes = [_take(path, bpm) for path in take_paths]
    usable = [take for take in takes if take is not None]
    if not usable:
        raise ValueError("join_takes needs at least one take with sound")
    target = round(target_duration * RATE)
    joined = _sequence(usable, target)[:target]
    _finish(joined)
    _write_wav(joined, output_path)
    return output_path


def _take(path: Path, bpm: float | None) -> _Take | None:
    audio = _decode(path)
    if audio.size == 0 or np.abs(audio).max() < _SILENCE:
        logger.warning("A generated take was silent; leaving it out of the join")
        return None
    tempo = float(bpm or detect_bpm(path) or _FALLBACK_BPM)
    downbeats = _downbeats(audio.mean(axis=1), tempo)
    return _Take(audio, *_bar_span(audio, downbeats))


def _bar_span(audio: np.ndarray, downbeats: np.ndarray) -> tuple[int, int]:
    """The first downbeat after the lead-in and the last one before the outro."""
    sound = np.flatnonzero(np.abs(audio).max(axis=1) > _SILENCE)
    lead_in, last_sound = int(sound[0]), int(sound[-1])
    latest_end = last_sound - int(_TAIL_GUARD_SECONDS * RATE)
    starts = downbeats[downbeats >= lead_in]
    ends = downbeats[downbeats <= latest_end]
    if starts.size and ends.size and ends[-1] - starts[0] > 2 * _half_fade():
        return int(starts[0]), int(ends[-1])
    # Too short for a bar grid: use the take as it sounds.
    return lead_in, last_sound


def _sequence(takes: list[_Take], target: int) -> np.ndarray:
    """Takes in order, repeated until ``target`` samples, each seam on a shared bar line."""
    half = _half_fade()
    first = takes[0]
    # The film opens on the first take's own opening, pickup included.
    joined = first.audio[: first.end + half].copy()
    queue = cycle(takes)
    next(queue)
    while joined.shape[0] < target + half:
        joined = _append(joined, next(queue), half)
    return joined


def _append(joined: np.ndarray, take: _Take, half: int) -> np.ndarray:
    """Crossfade ``take`` in, its first downbeat on the bar line ``half`` before the end."""
    head = _padded(take.audio, take.start - half, take.start + half)
    gain = _level_match(joined[: joined.shape[0] - half], take.audio[take.start :])
    angle = np.linspace(0, np.pi / 2, 2 * half, dtype=np.float32)[:, None]
    seam = joined[-2 * half :] * np.cos(angle) + head * gain * np.sin(angle)
    body = take.audio[take.start + half : take.end + half] * gain
    return np.concatenate([joined[: -2 * half], seam, body])


def _padded(audio: np.ndarray, start: int, end: int) -> np.ndarray:
    """``audio[start:end]``, zero-padded where the range runs off either edge."""
    out = np.zeros((end - start, audio.shape[1]), dtype=np.float32)
    lo, hi = max(start, 0), min(end, audio.shape[0])
    if hi > lo:
        out[lo - start : hi - start] = audio[lo:hi]
    return out


def _level_match(before: np.ndarray, after: np.ndarray) -> float:
    """The gain that brings the next take's opening to the level the music is at."""
    window = int(_LEVEL_WINDOW_SECONDS * RATE)
    then, now = _rms(before[-window:]), _rms(after[:window])
    if then <= _SILENCE or now <= _SILENCE:
        return 1.0
    limit = 10 ** (_MAX_GAIN_DB / 20)
    return float(np.clip(then / now, 1 / limit, limit))


def _rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(audio)))) if audio.size else 0.0


def _downbeats(mono: np.ndarray, bpm: float) -> np.ndarray:
    """Sample positions of the bar lines: a beat comb fitted near ``bpm``, its loudest beat of four."""
    onset = _onset_envelope(mono)
    period, phase = _fit_beat_grid(onset, 60.0 * RATE / _HOP / bpm)
    beats = np.arange(phase, onset.size - 1, period)
    strength = onset[np.round(beats).astype(int)]
    bar_phase = int(np.argmax([strength[i::_BEATS_PER_BAR].mean() for i in range(_BEATS_PER_BAR)]))
    bars = beats[bar_phase::_BEATS_PER_BAR]
    return np.array([_snap(onset, frame) * _HOP for frame in bars], dtype=np.int64)


def _onset_envelope(mono: np.ndarray) -> np.ndarray:
    """Rises in high-frequency energy per hop: drum hits, plucks and note attacks."""
    edge = np.diff(mono, prepend=mono[:1])
    frames = edge[: edge.size // _HOP * _HOP].reshape(-1, _HOP)
    energy = np.log1p(1000 * np.sqrt(np.mean(np.square(frames), axis=1)))
    return np.maximum(np.diff(energy, prepend=energy[:1]), 0)


def _fit_beat_grid(onset: np.ndarray, period: float) -> tuple[float, float]:
    """The (period, phase) in frames whose beat comb lands on the most onset energy.

    A generated take keeps close to the tempo it was asked for, so the search
    stays within a few percent of it rather than risking a half- or double-time grid.
    """
    best = (period, 0.0, -1.0)
    for candidate in period * np.linspace(0.97, 1.03, 25):
        ticks = np.arange(0, onset.size - candidate, candidate)
        for phase in np.arange(0, candidate, 1.0):
            score = onset[np.round(ticks + phase).astype(int) % onset.size].mean()
            if score > best[2]:
                best = (candidate, phase, score)
    return best[0], best[1]


def _snap(onset: np.ndarray, frame: float) -> int:
    """The strongest onset within a few frames of a grid line, against slow tempo drift."""
    centre = int(round(frame))
    lo, hi = max(centre - 3, 0), min(centre + 4, onset.size)
    return lo + int(np.argmax(onset[lo:hi]))


def _half_fade() -> int:
    return int(_CROSSFADE_SECONDS * RATE / 2)


def _finish(audio: np.ndarray) -> None:
    """A click-free start and the same two-second tail fade the other music paths use."""
    fade_in = min(int(0.05 * RATE), audio.shape[0])
    audio[:fade_in] *= np.linspace(0, 1, fade_in, dtype=np.float32)[:, None]
    fade_out = min(int(_FADE_OUT_SECONDS * RATE), audio.shape[0])
    audio[-fade_out:] *= np.linspace(1, 0, fade_out, dtype=np.float32)[:, None]


def _decode(path: Path) -> np.ndarray:
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
            "2",
            "-ar",
            str(RATE),
            "-",
        ],
        capture_output=True,
        check=True,
        timeout=300,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, 2).copy()


def _write_wav(audio: np.ndarray, output_path: Path) -> None:
    pcm = np.clip(audio, -1.0, 1.0).astype("<f4").tobytes()
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "f32le",
            "-ac",
            "2",
            "-ar",
            str(RATE),
            "-i",
            "-",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ],
        input=pcm,
        capture_output=True,
        check=True,
        timeout=300,
    )
