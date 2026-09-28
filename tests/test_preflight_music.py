"""`doctor` says when music is set to run on this machine and cannot."""

from __future__ import annotations

from immich_memories.config_loader import Config
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

    assert check_music(_lib_mode()).status is CheckStatus.OK


def test_no_local_music_backend_is_nothing_to_check():
    assert check_music(Config(ace_step={"enabled": False})).status is CheckStatus.SKIPPED
