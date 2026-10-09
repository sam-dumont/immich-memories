"""`auto install` on macOS ends with launchd's own answer about a LAN Immich (#2242)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from immich_memories.automation.local_network_check import CheckOutcome
from immich_memories.automation.system_scheduler import SchedulerInstallResult
from immich_memories.cli import main
from immich_memories.config_loader import Config

PYTHON = "/Users/me/.local/share/uv/python/cpython-3.12.14-macos-aarch64-none/bin/python3.12"


def _install(url: str, outcome: CheckOutcome, tmp_path: Path, platform: str = "launchd"):
    config = Config(immich={"url": url, "api_key": "k" * 12})
    installed = SchedulerInstallResult(platform=platform, files_written=[tmp_path / "shim"])
    with (
        # WHY: init_config_dir and get_config would touch the real home directory.
        patch("immich_memories.cli.init_config_dir"),
        patch("immich_memories.cli.get_config", return_value=config),
        # WHY: install_scheduler writes into the host's launchd directories.
        patch(
            "immich_memories.automation.system_scheduler.install_scheduler", return_value=installed
        ),
        patch(
            "immich_memories.automation.system_scheduler.resolve_disabled_launchd_label",
            return_value=None,
        ),
        # WHY: the check itself starts a LaunchAgent on the host.
        patch(
            "immich_memories.automation.local_network_check.run_check", return_value=outcome
        ) as ran,
        patch("immich_memories.config_loader.config_state_dir", return_value=tmp_path),
    ):
        result = CliRunner().invoke(main, ["auto", "install"], catch_exceptions=False)
    return result, ran


def test_a_passing_check_says_so(tmp_path):
    result, ran = _install("http://192.168.1.20:2283", CheckOutcome(True, True, PYTHON), tmp_path)

    assert ran.called
    assert "reach Immich on your local network" in result.output


def test_a_failing_check_names_the_interpreter_and_settings(tmp_path):
    outcome = CheckOutcome(
        False,
        True,
        PYTHON,
        advice=f"Allow {PYTHON} in System Settings > Privacy & Security > Local Network",
    )

    result, _ = _install("http://192.168.1.20:2283", outcome, tmp_path)

    assert PYTHON in result.output
    assert "Privacy & Security > Local Network" in result.output


def test_the_check_is_skipped_for_the_internet_and_for_other_platforms(tmp_path):
    outcome = CheckOutcome(True, True, PYTHON)

    _, internet = _install("https://photos.example.com", outcome, tmp_path)
    _, systemd = _install("http://192.168.1.20:2283", outcome, tmp_path, platform="systemd")

    assert not internet.called
    assert not systemd.called


def test_failed_check_prints_a_copyable_interpreter_path(tmp_path, monkeypatch):
    from immich_memories.cli._helpers import console

    monkeypatch.setattr(console, "width", 40)
    outcome = CheckOutcome(False, True, PYTHON, advice=f"Allow {PYTHON} in Local Network")
    result, _ = _install("http://192.168.1.20:2283", outcome, tmp_path)
    assert PYTHON in result.output.splitlines()
