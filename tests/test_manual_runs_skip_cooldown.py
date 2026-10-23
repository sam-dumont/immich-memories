"""A film somebody forces never holds back the scheduled one.

The cooldown and the daily timer pace the films nobody asked for. A film made on purpose
(`auto run --force`, **Run this suggestion**) is an extra: it still counts for the rotation
rules, but the next scheduled run comes as if it had not happened.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from immich_memories.automation.in_process_scheduler import InProcessScheduler
from immich_memories.automation.models import COOLDOWN_ACTIVE, AutoOutcome, AutoRunResult
from immich_memories.automation.runner import AutoRunner
from immich_memories.automation.state_store import AutomationStateStore
from immich_memories.automation.status import is_within_cooldown
from immich_memories.config.loader import Config
from immich_memories.db import open_store
from immich_memories.tracking.run_database import RunDatabase
from tests.auto_library_fake import (
    FakeGenerateChild,
    immich_serving,
    last_month,
    library_with_last_month,
    load_config_file,
)


@pytest.fixture
def child(tmp_path: Path):
    recorder = FakeGenerateChild(tmp_path / "films")
    # WHY: the `generate` child process; the stand-in records a finished film in the store.
    with patch("immich_memories.automation.runner._execute_generate", recorder):
        yield recorder


def _cooling(config: Config) -> bool:
    return is_within_cooldown(RunDatabase(open_store(config)), 24)


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class TestAForcedFilmStartsNoCooldown:
    @pytest.mark.feature("automation.forced-runs-skip-pacing")
    def test_auto_run_force_leaves_the_cooldown_where_it_was(
        self, tmp_path: Path, child: FakeGenerateChild
    ) -> None:
        config = load_config_file(tmp_path)

        with immich_serving(library_with_last_month()):
            made = AutoRunner(config).run_one(force=True)

        assert made.outcome is AutoOutcome.COMPLETED
        assert not _cooling(config)
        assert not AutoRunner(config).status().cooldown.active

    @pytest.mark.feature("automation.forced-runs-skip-pacing")
    def test_the_next_trigger_is_not_skipped_for_the_cooldown(
        self, tmp_path: Path, child: FakeGenerateChild
    ) -> None:
        config = load_config_file(tmp_path)

        with immich_serving(library_with_last_month()):
            AutoRunner(config).run_one(force=True)
            triggered = AutoRunner(config).start_one(reason="http trigger").execute()

        assert triggered.reason != COOLDOWN_ACTIVE

    @pytest.mark.feature("automation.forced-runs-skip-pacing")
    def test_a_picked_suggestion_leaves_the_cooldown_where_it_was(
        self, tmp_path: Path, child: FakeGenerateChild
    ) -> None:
        from immich_memories.automation.candidates import make_memory_key
        from immich_memories.web import mount_web
        from immich_memories.web.dependencies import current_config

        config = load_config_file(tmp_path)
        app = FastAPI()
        mount_web(app)
        app.dependency_overrides[current_config] = lambda: config
        key = make_memory_key("monthly_highlights", *last_month())

        with immich_serving(library_with_last_month()):
            started = TestClient(app).post("/api/v1/suggestions/run", json={"memory_key": key})
            state = AutomationStateStore(open_store(config))
            for _ in range(200):
                attempt = state.get_attempt(started.json()["id"])
                if attempt is not None and attempt.outcome is not AutoOutcome.RUNNING:
                    break
                time.sleep(0.05)

        assert attempt is not None
        assert attempt.outcome is AutoOutcome.COMPLETED
        assert not _cooling(config)


class TestAScheduledFilmStillStartsIt:
    @pytest.mark.feature("automation.forced-runs-skip-pacing")
    def test_an_unforced_run_starts_the_cooldown(
        self, tmp_path: Path, child: FakeGenerateChild
    ) -> None:
        config = load_config_file(tmp_path)

        with immich_serving(library_with_last_month()):
            made = AutoRunner(config).run_one()

        assert made.outcome is AutoOutcome.COMPLETED
        assert _cooling(config)

    @pytest.mark.feature("automation.forced-runs-skip-pacing")
    def test_a_trigger_starts_the_cooldown(self, tmp_path: Path, child: FakeGenerateChild) -> None:
        config = load_config_file(tmp_path)

        with immich_serving(library_with_last_month()):
            made = AutoRunner(config).start_one(reason="http trigger").execute()

        assert made.outcome is AutoOutcome.COMPLETED
        assert _cooling(config)


class TestTheDailyTimerAfterAForcedFilm:
    @pytest.mark.feature("automation.forced-runs-skip-pacing")
    def test_the_timer_still_makes_the_days_film(
        self, tmp_path: Path, child: FakeGenerateChild
    ) -> None:
        config = load_config_file(tmp_path, enabled=True, daily_at="09:00")
        with immich_serving(library_with_last_month()):
            AutoRunner(config).run_one(force=True)
        fired: list[str] = []

        def run_once(_config: Config) -> AutoRunResult:
            fired.append("fire")
            return AutoRunResult(outcome=AutoOutcome.COMPLETED, reason="generation completed")

        # The store stamps attempts with the real clock, so the timer's day is today.
        nine = datetime.now().astimezone().replace(hour=9, minute=0, second=5, microsecond=0)
        timer = InProcessScheduler(lambda: config, run_once=run_once, clock=_Clock(nine))
        asyncio.run(timer.tick())

        assert fired == ["fire"]
