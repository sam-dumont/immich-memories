"""A long film's bundled soundtrack is a varied playlist, not one looped track.

#2070: without ACE-Step, every Docker/NAS film used a single ~30 s bundled
track looped up to 20 times — a 10-minute film was one phrase on repeat.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from immich_memories.audio.bundled_music import bundled_playlist_for_mood


def _library(tmp_path: Path, mood: str, names: tuple[str, ...]) -> Path:
    """A stand-in for the installed music package: one folder per mood."""
    folder = tmp_path / mood
    folder.mkdir(parents=True)
    for name in names:
        (folder / f"{name}.opus").write_bytes(b"")
    return tmp_path


@pytest.fixture
def _fixed_duration(monkeypatch: pytest.MonkeyPatch):
    """Every bundled track reports a fixed 30 s duration.

    WHY: replaces the ffprobe read — the playlist's covering/ordering logic is
    what is under test here, not ffprobe's own correctness (held by the
    integration test that renders a real mix).
    """

    def _apply(seconds: float = 30.0) -> None:
        monkeypatch.setattr(
            "immich_memories.audio.bundled_music.get_audio_duration", lambda _p: seconds
        )

    return _apply


def test_a_short_film_stays_a_single_track(tmp_path: Path, _fixed_duration) -> None:
    """One track already covers the film: no playlist, no crossfade needed."""
    _fixed_duration(40.0)
    library = _library(tmp_path, "calm", ("a", "b", "c"))

    playlist = bundled_playlist_for_mood("calm", total_duration=20.0, library=library)

    assert len(playlist) == 1


def test_a_long_film_gets_several_tracks(tmp_path: Path, _fixed_duration) -> None:
    """A film far longer than any single track must draw on more than one."""
    _fixed_duration(30.0)
    library = _library(tmp_path, "calm", ("a", "b", "c"))

    playlist = bundled_playlist_for_mood("calm", total_duration=300.0, library=library, seed=1)

    assert len(playlist) > 1


def test_no_track_repeats_back_to_back_when_the_pool_allows_it(
    tmp_path: Path, _fixed_duration
) -> None:
    _fixed_duration(30.0)
    library = _library(tmp_path, "calm", ("a", "b", "c"))

    playlist = bundled_playlist_for_mood("calm", total_duration=300.0, library=library, seed=7)

    assert all(playlist[i] != playlist[i + 1] for i in range(len(playlist) - 1))


def test_the_playlist_covers_the_requested_duration(tmp_path: Path, _fixed_duration) -> None:
    _fixed_duration(30.0)
    library = _library(tmp_path, "calm", ("a", "b", "c"))

    playlist = bundled_playlist_for_mood("calm", total_duration=300.0, library=library, seed=3)

    assert sum(30.0 for _ in playlist) >= 300.0


def test_the_seed_makes_the_playlist_deterministic(tmp_path: Path, _fixed_duration) -> None:
    _fixed_duration(30.0)
    library = _library(tmp_path, "calm", ("a", "b", "c", "d"))

    first = bundled_playlist_for_mood("calm", total_duration=200.0, library=library, seed=42)
    second = bundled_playlist_for_mood("calm", total_duration=200.0, library=library, seed=42)

    assert first == second


def test_a_single_track_pool_still_covers_the_film_by_repeating(
    tmp_path: Path, _fixed_duration
) -> None:
    """Only one bundled track for the mood: repeat it, there is no variety to add."""
    _fixed_duration(30.0)
    library = _library(tmp_path, "calm", ("only",))

    playlist = bundled_playlist_for_mood("calm", total_duration=100.0, library=library)

    assert len(playlist) > 1
    assert all(track.stem == "only" for track in playlist)


def test_an_absent_library_returns_no_playlist(tmp_path: Path, _fixed_duration) -> None:
    playlist = bundled_playlist_for_mood("calm", total_duration=300.0, library=tmp_path / "absent")

    assert playlist == []


def test_unreadable_durations_degrade_to_one_track_instead_of_spinning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every candidate's duration comes back 0.0 (corrupt/garbage fixtures)."""
    monkeypatch.setattr("immich_memories.audio.bundled_music.get_audio_duration", lambda _p: 0.0)
    library = _library(tmp_path, "calm", ("a", "b"))

    playlist = bundled_playlist_for_mood("calm", total_duration=300.0, library=library)

    assert len(playlist) == 1
