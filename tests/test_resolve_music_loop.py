"""resolve_music plays one library track, looped to the film's length once it knows it.

A film never chains different bundled tracks or tracks from your folder: the one track
it picks is looped on its own bar lines (``loop_track``). A caller that cannot supply
``video_duration`` gets the track as it is, and the mixer loops it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from immich_memories.config.loader import Config
from immich_memories.generate_music import resolve_music


def _library(tmp_path: Path, mood: str, names: tuple[str, ...]) -> Path:
    folder = tmp_path / mood
    folder.mkdir(parents=True)
    for name in names:
        (folder / f"{name}.opus").write_bytes(b"")
    return tmp_path


def _config() -> Config:
    config = Config()
    config.ace_step.enabled = False
    config.musicgen.enabled = False
    return config


@pytest.fixture
def loops(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Path, float]]:
    """Every loop asked for, as (track, target seconds); fixture tracks read as 30 s."""
    asked: list[tuple[Path, float]] = []

    # WHY: replaces the FFmpeg bar-line loop; it has its own integration test.
    def _fake_loop(track: Path, target: float, output: Path) -> Path:
        asked.append((track, target))
        output.write_bytes(b"")
        return output

    monkeypatch.setattr("immich_memories.audio.take_join.loop_track", _fake_loop)
    # WHY: replaces the ffprobe duration read on the empty fixture tracks.
    monkeypatch.setattr("immich_memories.audio.mixer.get_audio_duration", lambda _p: 30.0)
    # WHY: mastering is FFmpeg work on real audio; the routing is under test here.
    monkeypatch.setattr(
        "immich_memories.audio.mastering.master_music_track", lambda source, _dest: source
    )
    return asked


def _resolve(library: Path, tmp_path: Path, video_duration: float | None) -> Path | None:
    return resolve_music(
        config=_config(),
        music_path=None,
        no_music=False,
        assembly_clips=[],
        run_output_dir=tmp_path / "run",
        memory_type=None,
        bundled_library=library,
        transition_overlap=0.0,
        video_duration=video_duration,
    ).path


def test_a_film_ten_times_its_track_loops_that_one_track(tmp_path: Path, loops) -> None:
    library = _library(tmp_path, "calm", ("a", "b", "c"))

    chosen = _resolve(library, tmp_path, 300.0)

    assert chosen is not None
    assert len(loops) == 1, "one track, looped; never a playlist"
    track, target = loops[0]
    assert track.parent.name == "calm"
    assert target == 300.0


def test_a_film_shorter_than_its_track_plays_it_as_it_is(tmp_path: Path, loops) -> None:
    library = _library(tmp_path, "calm", ("a", "b", "c"))

    chosen = _resolve(library, tmp_path, 20.0)

    assert chosen is not None and chosen.parent.name == "calm"
    assert loops == []


def test_without_a_video_duration_the_mixer_loops_the_track(tmp_path: Path, loops) -> None:
    library = _library(tmp_path, "calm", ("a", "b", "c"))

    chosen = _resolve(library, tmp_path, None)

    assert chosen is not None and chosen.parent.name == "calm"
    assert loops == []


def test_a_track_the_loop_cannot_read_still_plays(
    tmp_path: Path, loops, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = _library(tmp_path, "calm", ("a",))

    def _unreadable(*_args: object) -> Path:
        raise ValueError("loop_track needs a track with sound")

    # WHY: the bar-line loop's decode is the boundary that fails on a bad file.
    monkeypatch.setattr("immich_memories.audio.take_join.loop_track", _unreadable)

    chosen = _resolve(library, tmp_path, 300.0)

    assert chosen == library / "calm" / "a.opus"
