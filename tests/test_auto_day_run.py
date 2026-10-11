"""Which attempts are the day's run, and what happens to the ones a dead process left (#2365,
#2366, #2368).

The daily timer makes at most one film a day. Only an attempt that tried to make one may
take that place: a dry run, a stale click or a cooldown skip leaves it to the timer.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
import sqlalchemy as sa

from immich_memories.automation.in_process_scheduler import InProcessScheduler
from immich_memories.automation.models import AutomationAttempt, AutoOutcome, AutoRunResult
from immich_memories.automation.runner import AutoRunner
from immich_memories.automation.state_store import AutomationStateStore
from immich_memories.config_loader import Config
from immich_memories.db import open_store
from immich_memories.db.tables import automation_attempts
from immich_memories.tracking.models import RunMetadata
from immich_memories.tracking.run_database import RunDatabase
from tests.auto_library_fake import (
    FakeApprise,
    FakeGenerateChild,
    immich_serving,
    install_fake_apprise,
    library_with_last_month,
    load_config_file,
)


def _at_nine() -> datetime:
    # The store stamps attempts with the real clock, so the timer's day is today.
    return datetime.now().astimezone().replace(hour=9, minute=0, second=5, microsecond=0)


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _todays_attempts(config: Config) -> list[AutomationAttempt]:
    store = AutomationStateStore(open_store(config))
    with store.store.connect() as conn:
        ids = conn.execute(
            sa.select(automation_attempts.c.id).order_by(automation_attempts.c.started_at)
        ).scalars()
        attempts = [store.get_attempt(attempt_id) for attempt_id in ids]
    today = datetime.now().astimezone().date()
    return [a for a in attempts if a and a.started_at.astimezone().date() == today]


@pytest.fixture
def child(tmp_path: Path):
    recorder = FakeGenerateChild(tmp_path / "films")
    # WHY: the `generate` child process; the stand-in records a finished film in the store.
    with patch("immich_memories.automation.runner._execute_generate", recorder):
        yield recorder


class TestOnlyAnAttemptThatTriedToMakeAFilmIsTheDaysRun:
    @pytest.mark.feature("automation.dry-run-keeps-day")
    def test_a_dry_run_in_progress_at_the_daily_time_leaves_the_film_to_the_timer(
        self, tmp_path: Path, child: FakeGenerateChild
    ) -> None:
        config = load_config_file(tmp_path, enabled=True, daily_at="09:00")
        clock = _Clock(_at_nine())
        timer = InProcessScheduler(lambda: config, clock=clock)

        with immich_serving(library_with_last_month()):
            checking = AutoRunner(config).start_one(reason="web suggestion", dry_run=True)
            asyncio.run(timer.tick())
            checking.execute(dry_run=True)
            clock.now += timedelta(seconds=30)
            asyncio.run(timer.tick())

        outcomes = [a.outcome for a in _todays_attempts(config)]
        assert outcomes == [AutoOutcome.DRY_RUN, AutoOutcome.COMPLETED]
        assert len(child.commands) == 1

    @pytest.mark.feature("automation.dry-run-keeps-day")
    def test_a_stale_suggestion_click_leaves_the_film_to_the_timer(
        self, tmp_path: Path, child: FakeGenerateChild
    ) -> None:
        config = load_config_file(tmp_path, enabled=True, daily_at="09:00")
        timer = InProcessScheduler(lambda: config, clock=_Clock(_at_nine()))

        with immich_serving(library_with_last_month()):
            stale = AutoRunner(config).run_one(
                candidate_key="monthly_highlights:1999-01-01:1999-01-31:"
            )
            fired = asyncio.run(timer.tick())

        assert stale.outcome is AutoOutcome.FAILED
        assert fired
        assert [a.outcome for a in _todays_attempts(config)][-1] is AutoOutcome.COMPLETED


class TestTheTimersOwnCooldownSkip:
    @pytest.mark.feature("automation.scheduler-small-fixes")
    def test_the_day_is_made_once_the_cooldown_ends(self, tmp_path: Path) -> None:
        """Down at 09:00 yesterday, caught up at 14:00: today's film comes at 13:30."""
        config = load_config_file(tmp_path, enabled=True, daily_at="09:00")
        nine = _at_nine()
        yesterday_two_pm = (nine - timedelta(hours=19)).astimezone(UTC)
        RunDatabase(open_store(config)).save_run(
            RunMetadata(
                run_id="caught-up-yesterday",
                created_at=yesterday_two_pm,
                completed_at=yesterday_two_pm + timedelta(minutes=20),
                status="completed",
                source="auto",
                memory_type="monthly_highlights",
            )
        )
        answers = [
            AutoRunResult(outcome=AutoOutcome.SKIPPED, reason="cooldown active"),
            AutoRunResult(outcome=AutoOutcome.COMPLETED, reason="generation completed"),
        ]
        fired: list[str] = []

        def run_once(_config: Config) -> AutoRunResult:
            fired.append("fire")
            return answers[len(fired) - 1]

        clock = _Clock(nine)
        timer = InProcessScheduler(lambda: config, run_once=run_once, clock=clock)

        asyncio.run(timer.tick())
        assert timer.snapshot().next_run is not None
        assert timer.snapshot().next_run.date() == nine.date()
        clock.now = nine.replace(hour=12)
        asyncio.run(timer.tick())
        clock.now = nine.replace(hour=13, minute=31)
        asyncio.run(timer.tick())

        assert fired == ["fire", "fire"]
        assert timer.snapshot().last_outcome == "completed"


@pytest.fixture
def apprise(monkeypatch: pytest.MonkeyPatch) -> type[FakeApprise]:
    return install_fake_apprise(monkeypatch)


_NOTIFY = (
    "  notifications:\n    enabled: true\n    urls: ['ntfy://first/topic', 'ntfy://second/topic']\n"
)


class TestAnAttemptADeadProcessLeft:
    @pytest.mark.feature("automation.dead-attempts-end")
    def test_the_next_start_ends_it_interrupted_notifies_once_and_makes_the_day(
        self, tmp_path: Path, apprise: type[FakeApprise]
    ) -> None:
        config = load_config_file(tmp_path, _NOTIFY, enabled=True, daily_at="09:00")
        state = AutomationStateStore(open_store(config))
        # What a killed process leaves: the row, and no lease behind it.
        orphan = state.start_attempt(reason="daily wake")
        fired: list[Config] = []
        timer = InProcessScheduler(
            lambda: config,
            run_once=lambda c: (
                fired.append(c)
                or AutoRunResult(outcome=AutoOutcome.COMPLETED, reason="generation completed")
            ),
            clock=_Clock(_at_nine()),
        )

        asyncio.run(timer.tick())
        asyncio.run(timer.tick())

        settled = state.get_attempt(orphan.id)
        assert settled is not None and settled.outcome is AutoOutcome.FAILED
        assert "interrupted" in settled.reason
        assert apprise.delivered == [
            ("ntfy://first/topic", "Generation Failed: Automation"),
            ("ntfy://second/topic", "Generation Failed: Automation"),
        ]
        assert fired == [config]

    @pytest.mark.feature("automation.dead-attempts-end")
    def test_a_health_probe_reports_it_interrupted_but_writes_and_sends_nothing(
        self, tmp_path: Path, apprise: type[FakeApprise], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tests.web_server_fixtures import server_client

        config = load_config_file(tmp_path, _NOTIFY, enabled=True, daily_at="09:00")
        state = AutomationStateStore(open_store(config))
        orphan = state.start_attempt(reason="http trigger")

        server_client(monkeypatch, config).get("/health/ready")
        status = AutoRunner(config).status()

        assert status.last_attempt is not None and status.last_attempt.id == orphan.id
        assert status.last_attempt.outcome is AutoOutcome.FAILED
        stored = state.get_attempt(orphan.id)
        assert stored is not None and stored.outcome is AutoOutcome.RUNNING
        assert apprise.delivered == []

        timer = InProcessScheduler(
            lambda: config,
            run_once=lambda _c: AutoRunResult(outcome=AutoOutcome.COMPLETED, reason="done"),
            clock=_Clock(_at_nine()),
        )
        asyncio.run(timer.tick())
        asyncio.run(timer.tick())

        stored = state.get_attempt(orphan.id)
        assert stored is not None and stored.outcome is AutoOutcome.FAILED
        assert [url for url, _title in apprise.delivered] == [
            "ntfy://first/topic",
            "ntfy://second/topic",
        ]

    @pytest.mark.feature("automation.dead-attempts-end")
    def test_auto_status_on_the_command_line_ends_it(
        self, tmp_path: Path, apprise: type[FakeApprise]
    ) -> None:
        from click.testing import CliRunner

        from immich_memories.cli import auto_cmd

        config = load_config_file(tmp_path, _NOTIFY)
        state = AutomationStateStore(open_store(config))
        orphan = state.start_attempt(reason="http trigger")

        with immich_serving(library_with_last_month()):
            CliRunner().invoke(
                auto_cmd.auto, ["status", "--json"], obj={"config": config, "config_path": None}
            )

        stored = state.get_attempt(orphan.id)
        assert stored is not None and stored.outcome is AutoOutcome.FAILED
        assert len(apprise.delivered) == 2

    @pytest.mark.feature("automation.dead-attempts-end")
    def test_a_live_attempt_is_left_running(self, tmp_path: Path, apprise) -> None:
        config = load_config_file(tmp_path)
        live = AutoRunner(config).start_one(reason="http trigger")
        try:
            status = AutoRunner(config).status()
        finally:
            live.lease.release()

        assert status.last_attempt is not None
        assert status.last_attempt.outcome is AutoOutcome.RUNNING
