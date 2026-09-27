"""Automation attempts and notification health in the store."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from immich_memories.automation.models import AutoOutcome
from immich_memories.automation.notification_state import (
    NotificationFailureCategory,
    NotificationStateStore,
)
from immich_memories.automation.state_store import (
    AttemptAlreadyFinishedError,
    AutomationStateStore,
)
from immich_memories.operations.phases import OperationalPhase, PhaseEvent


def test_an_attempt_finishes_once_and_keeps_what_it_started_with(store):
    attempts = AutomationStateStore(store)
    started = attempts.start_attempt("daily wake", memory_key="trip:a", memory_type="trip")

    finished = attempts.finish_attempt(started.id, AutoOutcome.COMPLETED, "done", run_id="run-1")

    assert (finished.memory_key, finished.memory_type, finished.run_id) == (
        "trip:a",
        "trip",
        "run-1",
    )
    assert finished.finished_at is not None
    assert finished.started_at == started.started_at
    with pytest.raises(AttemptAlreadyFinishedError):
        attempts.finish_attempt(started.id, AutoOutcome.FAILED, "again")
    with pytest.raises(KeyError):
        attempts.finish_attempt("missing", AutoOutcome.FAILED, "nope")


def test_the_last_attempt_is_the_latest_started(store):
    attempts = AutomationStateStore(store)
    assert attempts.get_last_attempt() is None
    attempts.start_attempt("first")
    second = attempts.start_attempt("second")

    assert attempts.get_last_attempt().id == second.id


def test_failure_streaks_reset_on_success_and_ignore_skips(store):
    attempts = AutomationStateStore(store)

    def attempt(key: str, outcome: AutoOutcome) -> None:
        started = attempts.start_attempt("wake", memory_key=key)
        attempts.finish_attempt(started.id, outcome, outcome.value)

    attempt("trip:a", AutoOutcome.FAILED)
    attempt("trip:a", AutoOutcome.COMPLETED)
    attempt("trip:a", AutoOutcome.FAILED)
    attempt("year:2025", AutoOutcome.FAILED)
    attempt("year:2025", AutoOutcome.SKIPPED)
    attempt("year:2025", AutoOutcome.FAILED)

    streaks = attempts.consecutive_failures_by_key()

    assert {key: streak.count for key, streak in streaks.items()} == {"trip:a": 1, "year:2025": 2}
    assert streaks["year:2025"].last_failed_at.tzinfo is UTC


def test_an_attempt_phase_only_moves_forward(store):
    attempts = AutomationStateStore(store)
    started = attempts.start_attempt("wake")
    attempts.record_discovery(started.id)

    assert attempts.update_phase(started.id, PhaseEvent(OperationalPhase.RENDER, 0, 1, "r", 0.1))
    assert not attempts.update_phase(
        started.id, PhaseEvent(OperationalPhase.DOWNLOAD, 0, 1, "d", 0.0)
    )
    reread = attempts.get_attempt(started.id)
    assert reread.last_phase is OperationalPhase.RENDER
    assert [event["phase"] for event in reread.phase_events] == ["discovery", "render"]
    with pytest.raises(KeyError):
        attempts.update_phase("missing", PhaseEvent(OperationalPhase.RENDER, 0, 1, "r", 0.1))


def test_notification_health_cools_down_after_a_failure_until_a_success(store):
    state = NotificationStateStore(store)
    failed_at = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    assert state.get() is None
    assert state.is_cooling_down(24) is False

    failed = state.record_failure(NotificationFailureCategory.QUOTA, now=failed_at)

    assert failed.last_failure_at == failed_at
    assert failed.failure_message == NotificationFailureCategory.QUOTA.message
    assert state.is_cooling_down(24, now=failed_at + timedelta(hours=23)) is True
    assert state.is_cooling_down(24, now=failed_at + timedelta(hours=25)) is False

    healed = state.record_success(now=failed_at + timedelta(hours=1))

    assert healed.failure_category is NotificationFailureCategory.QUOTA
    assert state.is_cooling_down(24, now=failed_at + timedelta(hours=2)) is False
    assert healed.to_dict(cooldown_hours=24)["last_success_at"] == "2026-05-01T13:00:00+00:00"
