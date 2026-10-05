"""resolve_music builds a varied bundled playlist once it knows the film's length.

#2070: a caller that cannot supply ``video_duration`` must see the original
single-track pick, unchanged — this is what every pre-existing caller does.
"""

from __future__ import annotations

from pathlib import Path

from immich_memories.config_loader import Config
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


def test_without_a_video_duration_a_single_track_is_picked(tmp_path: Path, monkeypatch) -> None:
    """Every existing caller omits video_duration; behaviour must not change."""
    library = _library(tmp_path, "calm", ("a", "b", "c"))
    monkeypatch.setattr(
        "immich_memories.audio.mastering.master_music_track", lambda source, _dest: source
    )

    chosen = resolve_music(
        config=_config(),
        music_path=None,
        no_music=False,
        assembly_clips=[],
        run_output_dir=tmp_path,
        memory_type=None,
        bundled_library=library,
        transition_overlap=0.0,
    )

    assert chosen.path is not None
    assert chosen.path.parent.name == "calm"


def test_a_known_long_video_duration_builds_a_playlist(tmp_path: Path, monkeypatch) -> None:
    """A film far longer than one bundled track must crossfade several together."""
    library = _library(tmp_path, "calm", ("a", "b", "c"))

    # WHY: replaces the ffprobe duration read on the fixture tracks (empty
    # files) — the routing to the playlist branch is what is under test.
    monkeypatch.setattr("immich_memories.audio.bundled_music.get_audio_duration", lambda _p: 30.0)

    assembled_calls: list[tuple[int, float]] = []

    # WHY: replaces the FFmpeg crossfade assembly; records what it was asked to build.
    def _fake_assemble(block_paths, target_duration, output_path, crossfade_seconds=2.0):
        assembled_calls.append((len(block_paths), target_duration))
        output_path.write_bytes(b"")
        return output_path

    monkeypatch.setattr("immich_memories.audio.mixer.assemble_music", _fake_assemble)
    monkeypatch.setattr(
        "immich_memories.audio.mastering.master_music_track", lambda source, _dest: source
    )

    chosen = resolve_music(
        config=_config(),
        music_path=None,
        no_music=False,
        assembly_clips=[],
        run_output_dir=tmp_path,
        memory_type=None,
        bundled_library=library,
        transition_overlap=0.0,
        video_duration=300.0,
    )

    assert chosen.path is not None
    assert assembled_calls, "a long film must assemble a crossfaded playlist"
    track_count, target = assembled_calls[0]
    assert track_count > 1
    assert target == 300.0


def test_a_short_known_video_duration_skips_the_playlist(tmp_path: Path, monkeypatch) -> None:
    """A film shorter than one bundled track needs no crossfade assembly at all."""
    library = _library(tmp_path, "calm", ("a", "b", "c"))
    monkeypatch.setattr("immich_memories.audio.bundled_music.get_audio_duration", lambda _p: 40.0)

    assembled_calls: list[object] = []
    monkeypatch.setattr(
        "immich_memories.audio.mixer.assemble_music",
        lambda *a, **k: assembled_calls.append((a, k)),
    )
    monkeypatch.setattr(
        "immich_memories.audio.mastering.master_music_track", lambda source, _dest: source
    )

    chosen = resolve_music(
        config=_config(),
        music_path=None,
        no_music=False,
        assembly_clips=[],
        run_output_dir=tmp_path,
        memory_type=None,
        bundled_library=library,
        transition_overlap=0.0,
        video_duration=20.0,
    )

    assert chosen.path is not None
    assert not assembled_calls
