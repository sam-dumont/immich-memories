"""A film is 30 fps unless more than half of its video seconds are 50/60 fps footage (#2687)."""

from __future__ import annotations

from pathlib import Path

from immich_memories.processing.assembly_config import AssemblyClip
from immich_memories.processing.ffmpeg_prober import film_frame_rate


def _film(*parts: tuple[float, float]) -> tuple[list[AssemblyClip], dict[Path, float]]:
    clips, rates = [], {}
    for i, (fps, seconds) in enumerate(parts):
        path = Path(f"clip{i}.mp4")
        clips.append(AssemblyClip(path=path, duration=seconds))
        rates[path] = fps
    return clips, rates


def _rate(*parts: tuple[float, float]) -> int:
    clips, rates = _film(*parts)
    return film_frame_rate(clips, rates.get)


def test_one_fast_clip_among_slow_ones_does_not_raise_the_film():
    assert _rate((30, 50), (60, 5)) == 30


def test_a_half_split_stays_at_30():
    assert _rate((30, 10), (60, 10)) == 30


def test_most_seconds_at_60_make_a_60_film():
    assert _rate((30, 4), (59.94, 6)) == 60


def test_most_seconds_at_50_make_a_50_film():
    assert _rate((25, 4), (50, 6)) == 50


def test_slow_motion_counts_as_30():
    assert _rate((240, 30), (30, 10)) == 30
    assert _rate((120, 30), (60, 5)) == 30


def test_footage_all_at_24_or_25_keeps_its_rate():
    assert _rate((24, 5), (23.976, 5)) == 24
    assert _rate((25, 5)) == 25


def test_a_mix_with_30_fps_footage_plays_at_30():
    assert _rate((24, 5), (30, 5)) == 30
