"""`doctor` says when music is set to run on this machine and cannot."""

from __future__ import annotations

from immich_memories.audio.generators.ace_step_music_path import MusicPath
from immich_memories.config.loader import Config
from immich_memories.preflight import CheckStatus
from immich_memories.preflight_music import check_music


def _lib_mode() -> Config:
    return Config(ace_step={"enabled": True, "mode": "lib"})


def test_lib_mode_without_ace_step_installed_names_the_command(monkeypatch):
    # WHY: the checkout's sibling .venv-acestep and the importable library are the
    # install's state on disk; the test asks for a checkout that has neither.
    monkeypatch.setattr("immich_memories.preflight_music.isolated_python", lambda: None)
    monkeypatch.setattr("immich_memories.preflight_music.is_ace_step_importable", lambda: False)

    result = check_music(_lib_mode())

    assert result.status is CheckStatus.WARNING
    assert "make install-acestep" in (result.details or "")


def test_lib_mode_with_the_checkout_s_ace_step_environment_is_ready(monkeypatch, tmp_path):
    # WHY: as above; this checkout has its .venv-acestep.
    monkeypatch.setattr(
        "immich_memories.preflight_music.isolated_python", lambda: tmp_path / "python"
    )

    # WHY: the host's memory decides the path; this test is about the install
    monkeypatch.setattr(
        "immich_memories.preflight_music.music_path_for", lambda _settings: MusicPath(True)
    )

    assert check_music(_lib_mode()).status is CheckStatus.OK


def test_a_host_below_the_xl_bar_says_films_use_the_bundled_library(monkeypatch, tmp_path):
    # WHY: as above, plus the host-memory decision.
    monkeypatch.setattr(
        "immich_memories.preflight_music.isolated_python", lambda: tmp_path / "python"
    )
    monkeypatch.setattr(
        "immich_memories.preflight_music.music_path_for",
        lambda _settings: MusicPath(False, "this host has 32 GB; the bundled library plays"),
    )

    result = check_music(_lib_mode())

    assert result.status is CheckStatus.WARNING
    assert "bundled track" in result.message and "32 GB" in (result.details or "")


def test_api_mode_reports_what_the_server_runs(monkeypatch):
    # WHY: the server is the network boundary.
    monkeypatch.setattr(
        "immich_memories.preflight_music.music_path_for",
        lambda _settings: MusicPath(False, "the ACE-Step server runs acestep-v15-turbo, not XL"),
    )

    result = check_music(Config(ace_step={"enabled": True, "mode": "api"}))

    assert result.status is CheckStatus.WARNING
    assert "acestep-v15-turbo" in (result.details or "")


def test_no_local_music_backend_is_nothing_to_check():
    assert check_music(Config(ace_step={"enabled": False})).status is CheckStatus.SKIPPED
