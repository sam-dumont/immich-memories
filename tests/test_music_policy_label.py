"""The generate plan names the music the render will actually use (#2031)."""

from __future__ import annotations

from immich_memories.cli._generation_preview import music_policy
from immich_memories.config_loader import Config


def test_plan_says_bundled_when_no_generator_is_configured():
    config = Config()
    config.ace_step.enabled = False
    config.musicgen.enabled = False

    assert music_policy(config=config, music=None, no_music=False) == "bundled track"


def test_plan_names_your_music_folder_when_it_has_tracks(tmp_path):
    """A folder of your own music plays before the bundle, so the plan says so."""
    (tmp_path / "happy").mkdir()
    (tmp_path / "happy" / "mine.mp3").write_bytes(b"ID3")
    config = Config()
    config.ace_step.enabled = False
    config.musicgen.enabled = False
    config.audio.local_music_dir = str(tmp_path)

    label = music_policy(config=config, music=None, no_music=False)

    assert label == "your music folder (bundled tracks for moods it lacks)"
    assert str(tmp_path) not in label
