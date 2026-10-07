"""`auto status` names the scheduler that is actually in use (#2212)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from immich_memories.automation.last_trigger import read_last_trigger, record_trigger
from immich_memories.automation.scheduler_in_use import describe_scheduler
from immich_memories.automation.system_scheduler import SchedulerStatus
from immich_memories.cli import main
from immich_memories.config_loader import Config

UNKNOWN_CRON = SchedulerStatus(platform="crontab", installed=None, active=None)
NO_CRON = SchedulerStatus(platform="crontab", installed=False, active=None)


def _config(
    tmp_path: Path, *, automation: dict | None = None, server: dict | None = None
) -> Config:
    return Config(
        immich={"url": "http://immich.test:2283", "api_key": "test-key"},
        cache={"database": str(tmp_path / "s.db"), "directory": str(tmp_path / "cache")},
        automation=automation or {},
        server=server or {},
    )


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime.now().astimezone().replace(hour=hour, minute=minute, second=0, microsecond=0)


def test_the_built_in_timer_is_named_with_its_time_zone_and_next_firing(tmp_path: Path) -> None:
    config = _config(tmp_path, automation={"enabled": True, "daily_at": "07:45"})

    described = describe_scheduler(config, UNKNOWN_CRON, None, now=_at(6))

    assert described.in_use == ["built-in timer"]
    assert "built-in timer" in described.summary
    assert "07:45" in described.summary
    assert str(_at(6).tzinfo) in described.summary or _at(6).tzname() in described.summary
    assert "next firing" in described.summary
    assert "unknown" not in described.summary
    assert "crontab" not in described.summary


def test_after_the_slot_the_next_firing_is_tomorrow(tmp_path: Path) -> None:
    config = _config(tmp_path, automation={"enabled": True, "daily_at": "07:45"})

    described = describe_scheduler(config, NO_CRON, None, now=_at(9))

    assert described.next_run is not None
    assert described.next_run.date() > _at(9).date()


def test_a_trigger_token_names_the_external_trigger_and_its_last_call(tmp_path: Path) -> None:
    config = _config(tmp_path, server={"trigger_token": "secret-token"})
    record_trigger(config)

    described = describe_scheduler(config, UNKNOWN_CRON, read_last_trigger(config), now=_at(9))

    assert described.in_use == ["external trigger"]
    assert "external trigger (POST /api/trigger)" in described.summary
    assert "last trigger" in described.summary
    assert "secret-token" not in described.summary
    assert "unknown" not in described.summary


def test_a_trigger_token_with_no_call_yet_says_so(tmp_path: Path) -> None:
    config = _config(tmp_path, server={"trigger_token": "secret-token"})

    described = describe_scheduler(config, NO_CRON, None, now=_at(9))

    assert "no trigger yet" in described.summary


def test_an_installed_system_unit_is_named_by_its_manager() -> None:
    config = Config()
    unit = SchedulerStatus(platform="launchd", installed=True, active=True)

    described = describe_scheduler(config, unit, None, now=_at(9))

    assert described.in_use == ["launchd"]
    assert described.summary.startswith("launchd, installed, active")


def test_everything_in_use_is_listed_and_nothing_in_use_says_none() -> None:
    config = Config(automation={"enabled": True}, server={"trigger_token": "t"})
    unit = SchedulerStatus(platform="systemd", installed=True, active=True)

    both = describe_scheduler(config, unit, None, now=_at(6))
    none = describe_scheduler(Config(), NO_CRON, None, now=_at(6))

    assert both.in_use == ["built-in timer", "systemd", "external trigger"]
    assert none.in_use == []
    assert none.summary.startswith("none")


def test_auto_status_prints_the_scheduler_in_use_and_keeps_the_json_keys(tmp_path: Path) -> None:
    config = _config(tmp_path, automation={"enabled": True, "daily_at": "07:45"})

    with (
        patch("immich_memories.cli.init_config_dir"),
        patch("immich_memories.cli.get_config", return_value=config),
        patch(
            "immich_memories.automation.system_scheduler.get_scheduler_status",
            return_value=UNKNOWN_CRON,
        ),
        patch("immich_memories.automation.runner.AutoRunner.suggest", return_value=[]),
    ):
        human = CliRunner().invoke(main, ["auto", "status"], catch_exceptions=False)
        as_json = CliRunner().invoke(main, ["auto", "status", "--json"], catch_exceptions=False)

    scheduler_line = next(line for line in human.output.splitlines() if "Scheduler:" in line)
    assert "built-in timer" in scheduler_line
    assert "installation unknown" not in scheduler_line
    payload = json.loads(as_json.stdout)
    assert payload["scheduler"]["platform"] == "crontab"
    assert payload["scheduler"]["in_use"] == ["built-in timer"]
