"""Small scheduler fixes before 1.0 (#2368), each at what a user sees."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from immich_memories.automation.models import AutoOutcome
from immich_memories.automation.state_store import AutomationStateStore
from immich_memories.config_loader import Config
from immich_memories.db import open_store
from immich_memories.tracking.models import RunMetadata
from immich_memories.tracking.run_database import RunDatabase
from tests.auto_library_fake import (
    FakeApprise,
    FakeGenerateChild,
    fake_library,
    immich_serving,
    install_fake_apprise,
    library_with_last_month,
    load_config_file,
    suggest_json,
    suggest_output,
)

TODAY = date(2026, 6, 10)


def _config(tmp_path: Path) -> Config:
    return Config(
        immich={"url": "https://immich.example.test", "api_key": "key"},
        cache={"database": str(tmp_path / "runs.db"), "directory": str(tmp_path / "cache")},
        automation={"detect_trips": False},
    )


def _auto_run(config: Config, category: str, when: datetime, key: str = "earlier") -> None:
    RunDatabase(open_store(config)).save_run(
        RunMetadata(
            run_id=f"auto-{category}",
            created_at=when,
            completed_at=when + timedelta(minutes=20),
            status="completed",
            source="auto",
            memory_type="monthly_highlights",
            memory_category=category,
            memory_key=key,
            output_path=f"/films/{category}.mp4",
        )
    )


class TestOtherMonthFilmsKeepTheirOwnCooldown:
    """Backfill and person months render as monthly_highlights but keep their own cooldown."""

    def _monthly_score(self, config: Config) -> float:
        rows = suggest_json(config, fake_library({"2026-05": 80, "2026-04": 60}), TODAY)
        return next(r["score"] for r in rows if r["category"] == "monthly_review")

    @pytest.mark.parametrize("category", ["backfill", "person_monthly"])
    def test_a_missed_or_person_month_yesterday_leaves_the_monthly_score_alone(
        self, tmp_path: Path, category: str
    ) -> None:
        config = _config(tmp_path)
        before = self._monthly_score(config)
        _auto_run(config, category, datetime(2026, 6, 9, 9, tzinfo=UTC))

        assert self._monthly_score(config) == before

    def test_a_busy_month_film_yesterday_still_lowers_it(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        before = self._monthly_score(config)
        _auto_run(config, "activity_burst", datetime(2026, 6, 9, 9, tzinfo=UTC))

        assert self._monthly_score(config) < before


def _album(count: int) -> dict:
    return {
        "id": "album-1",
        "albumName": "Weekend",
        "assetCount": count,
        "shared": False,
        "startDate": "2026-05-01T09:00:00.000Z",
        "endDate": "2026-05-03T18:00:00.000Z",
    }


class TestAGrowingAlbumIsStillTheSameMemory:
    def _fail_twice(self, config: Config, key: str, reason: str = "generation failed") -> None:
        state = AutomationStateStore(open_store(config))
        for _ in range(2):
            attempt = state.start_attempt(reason="daily wake")
            outcome = AutoOutcome.SKIPPED if reason.startswith("nothing") else AutoOutcome.FAILED
            state.finish_attempt(attempt.id, outcome, reason, memory_key=key)

    def _library(self, count: int):
        client = fake_library({"2026-05": 80, "2026-04": 60})
        client.get_albums.return_value = [_album(count)]
        return client

    def test_failure_backoff_holds_after_one_more_picture(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        first = suggest_json(config, self._library(25), TODAY)
        album_key = next(r["memory_key"] for r in first if r["category"] == "album")
        self._fail_twice(config, album_key)

        rows = suggest_json(config, self._library(26), TODAY)

        assert "album" not in {r["category"] for r in rows}
        assert "Backing off Album" in suggest_output(config, self._library(26), TODAY)

    def test_the_seven_day_decline_hold_survives_growth(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        first = suggest_json(config, self._library(25), TODAY)
        album_key = next(r["memory_key"] for r in first if r["category"] == "album")
        self._fail_twice(config, album_key, "nothing worth a film: too few moments")

        rows = suggest_json(config, self._library(27), TODAY)

        assert "album" not in {r["category"] for r in rows}

    def test_a_filmed_album_still_counts_as_filmed_until_it_grows(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        first = suggest_json(config, self._library(25), TODAY)
        album_key = next(r["memory_key"] for r in first if r["category"] == "album")
        _auto_run(config, "album", datetime(2026, 5, 20, tzinfo=UTC), key=album_key)
        # Something else since, so the album is not held back as the previous category.
        _auto_run(config, "trip", datetime(2026, 5, 21, tzinfo=UTC), key="trip-key")

        assert "album" not in {
            r["category"] for r in suggest_json(config, self._library(30), TODAY)
        }
        assert "album" in {r["category"] for r in suggest_json(config, self._library(60), TODAY)}


@pytest.fixture
def apprise(monkeypatch: pytest.MonkeyPatch) -> type[FakeApprise]:
    return install_fake_apprise(monkeypatch, dead=frozenset({"ntfy://gone/topic"}))


def _delivered_to(apprise: type[FakeApprise]) -> list[str]:
    return [url for url, _title in apprise.delivered]


def _notify_config(*urls: str) -> Config:
    return Config(notifications={"enabled": True, "urls": list(urls)})


class TestNotifications:
    def test_one_dead_url_does_not_silence_the_working_one(self, apprise) -> None:
        from immich_memories.automation.notifications import send_configured_notification

        config = _notify_config("ntfy://working/topic", "ntfy://gone/topic")
        for _ in range(3):
            send_configured_notification(config, memory_type="monthly_highlights", success=True)

        assert _delivered_to(apprise).count("ntfy://working/topic") == 3

    def test_yesterdays_failure_does_not_swallow_todays_notice(self, apprise) -> None:
        from immich_memories.automation.notification_state import (
            NotificationFailureCategory,
            NotificationStateStore,
        )
        from immich_memories.automation.notifications import send_configured_notification

        config = _notify_config("ntfy://working/topic")
        # Yesterday's film finished later in the day than today's.
        NotificationStateStore(open_store(config)).record_failure(
            NotificationFailureCategory.TRANSPORT, now=datetime.now(tz=UTC) - timedelta(hours=22)
        )

        send_configured_notification(config, memory_type="monthly_highlights", success=True)

        assert _delivered_to(apprise) == ["ntfy://working/topic"]

    def test_a_failure_still_pauses_a_burst_of_notices(self, apprise) -> None:
        from immich_memories.automation.notification_state import (
            NotificationFailureCategory,
            NotificationStateStore,
        )
        from immich_memories.automation.notifications import send_configured_notification

        config = _notify_config("ntfy://working/topic")
        NotificationStateStore(open_store(config)).record_failure(
            NotificationFailureCategory.QUOTA, now=datetime.now(tz=UTC) - timedelta(hours=2)
        )

        send_configured_notification(config, memory_type="monthly_highlights", success=True)

        assert _delivered_to(apprise) == []


@pytest.fixture
def child(tmp_path: Path):
    recorder = FakeGenerateChild(tmp_path / "films")
    # WHY: the `generate` child process; the stand-in records a finished film in the store.
    with patch("immich_memories.automation.runner._execute_generate", recorder):
        yield recorder


def _web(config: Config) -> TestClient:
    from immich_memories.web import mount_web
    from immich_memories.web.dependencies import current_config

    app = FastAPI()
    mount_web(app)
    app.dependency_overrides[current_config] = lambda: config
    return TestClient(app)


def _wait_for(config: Config, attempt_id: str):
    state = AutomationStateStore(open_store(config))
    for _ in range(200):
        attempt = state.get_attempt(attempt_id)
        if attempt is not None and attempt.outcome is not AutoOutcome.RUNNING:
            return attempt
        asyncio.run(asyncio.sleep(0.05))
    return state.get_attempt(attempt_id)


class TestRunningASuggestion:
    def test_a_picked_suggestion_is_made_the_day_after_an_automatic_film(
        self, tmp_path: Path, child: FakeGenerateChild
    ) -> None:
        from immich_memories.automation.candidates import make_memory_key
        from tests.auto_library_fake import last_month

        config = load_config_file(tmp_path)
        _auto_run(config, "trip", datetime.now(tz=UTC) - timedelta(hours=20), key="trip-key")
        key = make_memory_key("monthly_highlights", *last_month())

        with immich_serving(library_with_last_month()):
            started = _web(config).post("/api/v1/suggestions/run", json={"memory_key": key})
            attempt = _wait_for(config, started.json()["id"])

        assert attempt is not None
        assert (attempt.outcome, attempt.reason) == (AutoOutcome.COMPLETED, "generation completed")


class TestTriggerStatusMidRun:
    def test_the_run_the_child_opened_shows_while_the_attempt_runs(self, tmp_path: Path) -> None:
        from immich_memories.web.trigger import register_trigger_routes

        config = load_config_file(tmp_path, "server:\n  trigger_token: workflow-token\n")
        attempt = AutomationStateStore(open_store(config)).start_attempt(reason="http trigger")
        RunDatabase(open_store(config)).save_run(
            RunMetadata(
                run_id="child-run",
                created_at=datetime.now(tz=UTC),
                status="running",
                source="auto",
                automation_attempt_id=attempt.id,
            )
        )
        app = FastAPI()
        register_trigger_routes(app, submit=lambda _started: None)

        body = (
            TestClient(app)
            .get(f"/api/trigger/{attempt.id}", headers={"x-api-key": "workflow-token"})
            .json()
        )

        assert body["state"] == "running"
        assert body["run"] is not None and body["run"]["run_id"] == "child-run"
