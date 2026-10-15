"""Keys that leave the documented config keep working until 2.0, and are named when set."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from immich_memories.config.loader import Config
from immich_memories.config.sources import describe_settings


@pytest.fixture(autouse=True)
def fresh_warnings(monkeypatch: pytest.MonkeyPatch) -> None:
    # WHY: each warning is said once per process; every test here is its own process.
    monkeypatch.setattr("immich_memories.config.unsupported._said", set())


def _load(tmp_path: Path, text: str) -> Config:
    path = tmp_path / "config.yaml"
    path.write_text(text)
    return Config.from_yaml(path, stored={})


def _warnings(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


def test_a_preparation_tier_in_the_file_is_named_and_the_tier_decides(tmp_path, caplog):
    config = _load(
        tmp_path, "tier: basic\nadvanced:\n  editorial:\n    preparation:\n      tier: full\n"
    )

    assert config.editorial.preparation.tier == "no_captions"
    said = _warnings(caplog)
    assert "editorial.preparation.tier is no longer supported" in said
    assert "choose tier: basic, gpu or full" in said
    assert "2.0" in said


@pytest.mark.parametrize("key", ["reader", "laya_audience", "detectors_enabled"])
def test_every_tier_owned_key_is_named(tmp_path, caplog, key):
    value = "model" if key == "reader" else "true"
    _load(tmp_path, f"tier: basic\nadvanced:\n  editorial:\n    {key}: {value}\n")

    assert f"editorial.{key} is no longer supported" in _warnings(caplog)


def test_an_internal_knob_still_works_and_is_named_without_its_value(tmp_path, caplog):
    config = _load(tmp_path, "photos:\n  burst_hash_threshold: 11\n")

    assert config.photos.burst_hash_threshold == 11
    said = _warnings(caplog)
    assert "photos.burst_hash_threshold is no longer supported" in said
    assert "11" not in said


def test_a_config_that_sets_none_of_them_says_nothing(tmp_path, caplog):
    _load(tmp_path, "tier: gpu\nphotos:\n  duration: 5\n")

    assert "no longer supported" not in _warnings(caplog)


def test_a_generator_hemisphere_is_honoured_and_names_its_replacement(tmp_path, caplog):
    from immich_memories.audio.text_mood import music_hemisphere

    config = _load(
        tmp_path,
        "trips:\n  homebase_latitude: -33.9\n  homebase_longitude: 151.2\n"
        "advanced:\n  musicgen:\n    hemisphere: north\n",
    )

    assert music_hemisphere(config) == "north"
    assert "trips.homebase_latitude decides it now" in _warnings(caplog)


def test_music_reads_seasons_in_the_home_base_hemisphere(tmp_path):
    from immich_memories.audio.text_mood import music_hemisphere

    south = _load(tmp_path, "trips:\n  homebase_latitude: -33.9\n  homebase_longitude: 151.2\n")
    unset = _load(tmp_path, "")

    assert music_hemisphere(south) == "south"
    assert music_hemisphere(unset) == "north"


def test_the_settings_list_hides_them_unless_something_sets_them(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("speech:\n  vad_threshold: 0.4\n")
    config = Config.from_yaml(path, stored={})

    keys = {entry.key for entry in describe_settings(config, path=path, stored_keys=set())}

    assert "speech.vad_threshold" in keys
    assert "speech.min_silence_ms" not in keys
    assert "editorial.preparation.tier" not in keys
    assert "tier" in keys


def test_the_automation_upload_pair_lands_on_upload_and_is_named(tmp_path, caplog):
    config = _load(
        tmp_path,
        "advanced:\n  automation:\n    upload_to_immich: true\n    album_name: Robots\n",
    )

    assert config.upload.enabled is True
    assert config.upload.album_name == "Robots"
    said = _warnings(caplog)
    assert "automation.upload_to_immich is no longer supported: use upload.enabled" in said
    assert "automation.album_name is no longer supported: use upload.album_name" in said
    assert "Robots" not in said


def test_an_upload_album_of_its_own_wins_and_a_written_default_does_not(tmp_path):
    # Older releases wrote `upload.enabled: false` into every file; that is not a choice.
    config = _load(
        tmp_path,
        "upload:\n  enabled: false\n  album_name: Films\n"
        "advanced:\n  automation:\n    upload_to_immich: true\n    album_name: Robots\n",
    )

    assert config.upload.enabled is True
    assert config.upload.album_name == "Films"


def test_a_lan_bind_without_sign_in_is_no_longer_a_setting(tmp_path, caplog):
    config = _load(
        tmp_path,
        "advanced:\n  auth:\n    enabled: false\n  server:\n    allow_unauthenticated_lan: true\n",
    )

    assert config.server.effective_host(auth_enabled=False) == "127.0.0.1"
    said = _warnings(caplog)
    assert "server.allow_unauthenticated_lan" in said
    assert "localhost only" in said


@pytest.mark.parametrize("section", ["musicgen", "ace_step"])
def test_the_generators_take_count_is_ignored_for_max_regenerations(tmp_path, caplog, section):
    from immich_memories.audio.music_generator_client import MusicGenClientConfig

    config = _load(tmp_path, f"advanced:\n  {section}:\n    num_versions: 5\n")

    assert f"{section}.num_versions is no longer supported" in _warnings(caplog)
    assert "audio.max_regenerations" in _warnings(caplog)
    assert MusicGenClientConfig.from_app_config(config.musicgen).num_versions == 3


@pytest.mark.parametrize(
    "key",
    [
        "analysis.optimal_clip_duration",
        "analysis.min_source_short_side",
        "analysis.max_album_assets",
        "title_screens.title_duration",
        "title_screens.month_divider_duration",
        "title_screens.ending_duration",
        "title_screens.month_divider_threshold",
        "llm.preflight_timeout_seconds",
    ],
)
def test_tuning_the_maintainer_moved_out_is_read_and_named(tmp_path, caplog, key):
    section, field = key.split(".")
    value = 3  # inside every one of their bounds
    config = _load(tmp_path, f"advanced:\n  {section}:\n    {field}: {value}\n")

    assert getattr(getattr(config, section), field) == value
    assert f"{key} is no longer supported" in _warnings(caplog)
