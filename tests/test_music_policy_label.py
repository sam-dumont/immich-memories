"""The generate plan names the music the render will actually use (#2031)."""

from __future__ import annotations

from immich_memories.cli._generation_preview import music_policy
from immich_memories.config_loader import Config


def test_plan_says_bundled_when_no_generator_is_configured():
    config = Config()
    config.ace_step.enabled = False
    config.musicgen.enabled = False

    assert music_policy(config=config, music=None, no_music=False) == "bundled track"
