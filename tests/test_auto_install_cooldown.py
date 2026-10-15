"""`auto install` leaves the cooldown to the config unless asked (#2364)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from immich_memories.cli import main


def _show(tmp_path: Path, *flags: str) -> str:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("advanced:\n  automation:\n    cooldown_hours: 72\n")
    # WHY: the host's PATH; show prints nothing when the command is not installed.
    with patch(
        "immich_memories.automation.system_scheduler.shutil.which",
        return_value="/usr/local/bin/immich-memories",
    ):
        result = CliRunner().invoke(
            main, ["--config", str(config_path), "auto", "install", "--show", *flags]
        )
    assert result.exit_code == 0, result.output
    return result.output


@pytest.mark.feature("automation.install-cooldown-hours")
def test_the_installed_command_leaves_the_cooldown_to_the_config(tmp_path: Path) -> None:
    shown = _show(tmp_path)

    assert "auto run" in shown or "<string>run</string>" in shown
    assert "--cooldown" not in shown


@pytest.mark.feature("automation.install-cooldown-hours")
def test_an_explicit_cooldown_is_still_written(tmp_path: Path) -> None:
    shown = _show(tmp_path, "--cooldown", "12")

    assert "--cooldown" in shown
    assert "12" in shown


@pytest.mark.feature("automation.install-cooldown-hours")
def test_the_scheduled_command_honours_the_configured_cooldown(tmp_path: Path) -> None:
    import json
    from datetime import UTC, datetime, timedelta

    from immich_memories.config.loader import Config
    from immich_memories.db import open_store
    from immich_memories.tracking.models import RunMetadata
    from immich_memories.tracking.run_database import RunDatabase

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"cache:\n  database: {tmp_path / 'runs.db'}\n  directory: {tmp_path / 'cache'}\n"
        "advanced:\n  automation:\n    cooldown_hours: 72\n"
    )
    yesterday = datetime.now(tz=UTC) - timedelta(hours=30)
    RunDatabase(open_store(Config.from_yaml(config_path))).save_run(
        RunMetadata(
            run_id="yesterday",
            created_at=yesterday,
            completed_at=yesterday + timedelta(minutes=20),
            status="completed",
            source="auto",
            memory_type="monthly_highlights",
        )
    )
    # What the installed job runs, now that it carries no --cooldown of its own.
    result = CliRunner().invoke(main, ["--config", str(config_path), "auto", "run", "--quiet"])

    decided = json.loads(result.output.strip().splitlines()[-1])
    assert (decided["outcome"], decided["reason"]) == ("skipped", "cooldown active")
