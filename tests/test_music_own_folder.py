"""Your own music folder (`audio.local_music_dir`) feeds films, picked by mood like the bundle.

The folder used to be read only by the `music` command; a film always played a bundled
track. Laid out like the bundle, one subfolder per mood, it now takes the bundle's place
for every mood it has, and the bundle covers the moods it lacks.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import pytest

from immich_memories.audio.bundled_music import music_library_for_mood
from immich_memories.config_loader import Config
from immich_memories.generate_music import resolve_music


def _tone(path: Path) -> Path:
    """A real, one-second audio file, so mastering and probing run as they do for users."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(  # noqa: S603 - fixed argv
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=1", str(path)],  # noqa: S607
        check=True,
        capture_output=True,
    )
    return path


def _library(root: Path, label: str, moods: tuple[str, ...]) -> Path:
    for mood in moods:
        _tone(root / mood / f"{label}-{mood}.wav")
    return root


def _config(own_folder: Path) -> Config:
    config = Config()
    config.ace_step.enabled = config.musicgen.enabled = False
    config.audio.local_music_dir = str(own_folder)
    return config


def _film_music(config: Config, bundled: Path, tmp_path: Path, memory_type: str) -> Path:
    selection = resolve_music(
        config,
        None,
        no_music=False,
        assembly_clips=[],
        run_output_dir=tmp_path / "run",
        memory_type=memory_type,
        bundled_library=bundled,
        transition_overlap=0.0,
    )
    assert selection.path is not None
    return selection.path


# A monthly film reads as playful, which the bundle serves from its happy folder.
def test_a_film_plays_a_track_from_your_folder_for_its_mood(tmp_path):
    own = _library(tmp_path / "own", "own", ("happy", "calm"))
    bundled = _library(tmp_path / "bundled", "bundled", ("happy", "calm"))

    played = _film_music(_config(own), bundled, tmp_path, "monthly_highlights")

    assert played.name == "mastered_own-happy.wav"


def test_a_mood_your_folder_lacks_plays_the_bundled_track(tmp_path):
    own = _library(tmp_path / "own", "own", ("calm",))
    bundled = _library(tmp_path / "bundled", "bundled", ("happy", "calm"))

    played = _film_music(_config(own), bundled, tmp_path, "monthly_highlights")

    assert played.name == "mastered_bundled-happy.wav"


def test_an_empty_or_missing_folder_plays_the_bundled_track(tmp_path):
    bundled = _library(tmp_path / "bundled", "bundled", ("happy",))
    (tmp_path / "empty" / "happy").mkdir(parents=True)

    for own in (tmp_path / "absent", tmp_path / "empty"):
        played = _film_music(_config(own), bundled, tmp_path, "monthly_highlights")
        assert played.name == "mastered_bundled-happy.wav"


def test_a_folder_named_after_the_mood_itself_is_used(tmp_path):
    """The bundle serves playful from happy; your own playful folder is taken as it is."""
    own = tmp_path / "own"
    _tone(own / "playful" / "mine.wav")
    _tone(own / "happy" / "other.wav")

    assert music_library_for_mood("playful", own, None) == own
    from immich_memories.audio.bundled_music import bundled_track_for_mood

    assert bundled_track_for_mood("playful", library=own) == own / "playful" / "mine.wav"


def test_a_mood_neither_library_has_picks_from_your_folder(tmp_path):
    own = _library(tmp_path / "own", "own", ("calm",))
    bundled = _library(tmp_path / "bundled", "bundled", ("happy",))

    assert music_library_for_mood("inspiring", own, bundled) == own
    assert music_library_for_mood("inspiring", own, None) == own
    assert music_library_for_mood("happy", own, bundled) == bundled


def test_a_working_generator_keeps_priority_over_your_folder(tmp_path, monkeypatch):
    from immich_memories.audio.music_generator_models import GeneratedMusic

    generated = _tone(tmp_path / "generated.wav")
    config = _config(_library(tmp_path / "own", "own", ("happy",)))
    config.ace_step.enabled = True
    # WHY: stands in for the ACE-Step backend, which needs a model server.
    monkeypatch.setattr(
        "immich_memories.generate_music.auto_generate_music",
        lambda *_args, **_kwargs: GeneratedMusic(full_mix=generated),
    )

    played = _film_music(config, tmp_path / "no-bundle", tmp_path, "monthly_highlights")

    assert played == generated


def test_the_log_never_prints_the_folder_from_the_config(tmp_path, caplog):
    secret_folder = tmp_path / "private-folder-name"
    bundled = _library(tmp_path / "bundled", "bundled", ("happy",))

    with caplog.at_level(logging.DEBUG, logger="immich_memories.audio.bundled_music"):
        _film_music(_config(secret_folder), bundled, tmp_path, "monthly_highlights")
        _library(secret_folder, "own", ("happy",))
        _film_music(_config(secret_folder), bundled, tmp_path, "monthly_highlights")

    assert "music folder" in caplog.text
    assert "private-folder-name" not in caplog.text


@pytest.mark.parametrize(("named", "level"), [(True, logging.WARNING), (False, logging.DEBUG)])
def test_a_missing_folder_warns_only_when_someone_named_it(tmp_path, caplog, named, level):
    with caplog.at_level(logging.DEBUG, logger="immich_memories.audio.bundled_music"):
        music_library_for_mood("happy", tmp_path / "absent", None, own_library_named=named)

    assert [record.levelno for record in caplog.records] == [level]


def test_a_failed_generator_names_your_folder_as_the_stand_in(tmp_path, monkeypatch):
    """The fallback warning says where the track came from, not "bundled" for your own."""
    own = _library(tmp_path / "own", "own", ("happy",))
    config = _config(own)
    config.ace_step.enabled = True

    def unreachable(*_args, **_kwargs):
        raise ConnectionError("unreachable")

    # WHY: stands in for the ACE-Step backend failing, which needs a model server.
    monkeypatch.setattr("immich_memories.generate_music.auto_generate_music", unreachable)

    selection = resolve_music(
        config,
        None,
        no_music=False,
        assembly_clips=[],
        run_output_dir=tmp_path / "run",
        memory_type="monthly_highlights",
        bundled_library=_library(tmp_path / "bundled", "bundled", ("happy",)),
        transition_overlap=0.0,
    )

    assert selection.path is not None and selection.path.name == "mastered_own-happy.wav"
    assert selection.warning is not None
    assert "used a track from your music folder instead" in selection.warning
    assert "bundled" not in selection.warning
    assert str(own) not in selection.warning
