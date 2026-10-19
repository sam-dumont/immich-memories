"""Automation attempts, kept in the store: what the nightly runner tried and how it ended."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import sqlalchemy as sa

from immich_memories.automation.candidates import memory_identity
from immich_memories.automation.models import (
    DECLINED_REASON,
    DRY_RUN_MARK,
    INTERRUPTED_REASON,
    NO_ELIGIBLE_CANDIDATES,
    STALE_CANDIDATE_REASON,
    AutomationAttempt,
    AutoOutcome,
)
from immich_memories.db import Store, from_db, open_store, to_db
from immich_memories.db.tables import attempt_phase_events, automation_attempts
from immich_memories.operations.phases import OperationalPhase, PhaseEvent
from immich_memories.tracking.phase_rows import advance_phase, read_phase_events

logger = logging.getLogger(__name__)

_ATTEMPTS = automation_attempts.c


@dataclass(frozen=True)
class FailureStreak:
    """How many times a memory key has failed since it last succeeded."""

    count: int
    last_failed_at: datetime | None
    # The period was read and held nothing worth a film: it will not change by tomorrow.
    declined: bool = False


class AttemptAlreadyFinishedError(RuntimeError):
    """Raised when a caller tries to replace an attempt's terminal result."""


def _row_to_attempt(row: Mapping[Any, Any]) -> AutomationAttempt:
    started_at = from_db(row["started_at"])
    assert started_at is not None
    return AutomationAttempt(
        id=row["id"],
        started_at=started_at,
        finished_at=from_db(row["finished_at"]),
        outcome=AutoOutcome(row["outcome"]),
        reason=row["reason"],
        candidate_category=row["candidate_category"],
        memory_type=row["memory_type"],
        memory_key=row["memory_key"],
        run_id=row["run_id"],
        error=row["error"],
        last_phase=OperationalPhase(row["last_phase"]) if row["last_phase"] else None,
    )


class AutomationStateStore:
    """Read and update automation attempt state without replacing start rows."""

    def __init__(self, store: Store | None = None):
        self.store = store or open_store()

    def start_attempt(
        self,
        reason: str,
        *,
        candidate_category: str | None = None,
        memory_type: str | None = None,
        memory_key: str | None = None,
    ) -> AutomationAttempt:
        """Insert and return a new running attempt."""
        attempt = AutomationAttempt(
            id=str(uuid4()),
            started_at=datetime.now(tz=UTC),
            finished_at=None,
            outcome=AutoOutcome.RUNNING,
            reason=reason,
            candidate_category=candidate_category,
            memory_type=memory_type,
            memory_key=memory_key,
        )
        with self.store.begin() as conn:
            conn.execute(
                sa.insert(automation_attempts),
                [
                    {
                        "id": attempt.id,
                        "started_at": to_db(attempt.started_at),
                        "finished_at": None,
                        "outcome": attempt.outcome.value,
                        "reason": attempt.reason,
                        "candidate_category": attempt.candidate_category,
                        "memory_type": attempt.memory_type,
                        "memory_key": attempt.memory_key,
                        "run_id": None,
                        "error": None,
                        "last_phase": None,
                        "phase_events": [],
                    }
                ],
            )
        return attempt

    def update_phase(self, attempt_id: str, event: PhaseEvent) -> bool:
        """Persist a forward-only phase update for one exact automation attempt."""
        with self.store.begin() as conn:
            advanced = advance_phase(
                conn,
                automation_attempts,
                _ATTEMPTS.id,
                attempt_id,
                event,
                attempt_phase_events.c.attempt_id,
            )
        if advanced is None:
            raise KeyError(f"Unknown automation attempt: {attempt_id}")
        return advanced

    def record_discovery(self, attempt_id: str) -> None:
        """Start candidate discovery without making telemetry decision-critical."""
        event = PhaseEvent(
            OperationalPhase.DISCOVERY,
            0,
            0,
            "Discovering daily memory candidates",
            0.0,
        )
        try:
            self.update_phase(attempt_id, event)
        except Exception:  # WHY: status persistence cannot abort the daily decision
            logger.warning("Could not persist automation discovery phase")

    def finish_attempt(
        self,
        attempt_id: str,
        outcome: AutoOutcome,
        reason: str,
        *,
        candidate_category: str | None = None,
        memory_type: str | None = None,
        memory_key: str | None = None,
        run_id: str | None = None,
        error: str | None = None,
    ) -> AutomationAttempt:
        """Set terminal fields once.

        Raises:
            KeyError: If ``attempt_id`` does not exist.
            AttemptAlreadyFinishedError: If the attempt is already terminal.
        """
        if outcome is AutoOutcome.RUNNING:
            raise ValueError("RUNNING is not a terminal automation outcome")

        finished_at = datetime.now(tz=UTC)
        # A field the finish does not name keeps what the start recorded.
        kept = {
            "candidate_category": candidate_category,
            "memory_type": memory_type,
            "memory_key": memory_key,
            "run_id": run_id,
        }
        values = {
            "finished_at": to_db(finished_at),
            "outcome": outcome.value,
            "reason": reason,
            "error": error,
        } | {name: value for name, value in kept.items() if value is not None}
        with self.store.begin() as conn:
            result = conn.execute(
                sa.update(automation_attempts)
                .where(_ATTEMPTS.id == attempt_id, _ATTEMPTS.outcome == AutoOutcome.RUNNING.value)
                .values(values)
            )
            if result.rowcount != 1:
                existing = conn.execute(
                    sa.select(_ATTEMPTS.outcome).where(_ATTEMPTS.id == attempt_id)
                ).scalar()
                if existing is None:
                    raise KeyError(f"Unknown automation attempt: {attempt_id}")
                raise AttemptAlreadyFinishedError(
                    f"Automation attempt already finished: {attempt_id} ({existing})"
                )
            row = (
                conn.execute(sa.select(automation_attempts).where(_ATTEMPTS.id == attempt_id))
                .mappings()
                .one()
            )
        return _row_to_attempt(row)

    def has_running_attempt(self) -> bool:
        """Whether any attempt reads `running`: live, or left so by a process that died."""
        with self.store.connect() as conn:
            found = conn.execute(
                sa.select(_ATTEMPTS.id).where(_ATTEMPTS.outcome == AutoOutcome.RUNNING.value)
            ).first()
        return found is not None

    def interrupt_running_attempts(self) -> list[AutomationAttempt]:
        """End every attempt still `running` as interrupted; the caller holds the lease.

        Only the holder of the automation lease may call this: with the lease taken,
        nothing else can be running, so a `running` row belongs to a process that died.
        """
        with self.store.begin() as conn:
            ids = list(
                conn.execute(
                    sa.select(_ATTEMPTS.id).where(_ATTEMPTS.outcome == AutoOutcome.RUNNING.value)
                ).scalars()
            )
        ended = []
        for attempt_id in ids:
            try:
                ended.append(
                    self.finish_attempt(
                        attempt_id, AutoOutcome.FAILED, INTERRUPTED_REASON, error=INTERRUPTED_REASON
                    )
                )
            except AttemptAlreadyFinishedError:
                continue
        return ended

    def get_attempt(self, attempt_id: str) -> AutomationAttempt | None:
        """Return one attempt by id, or None when nothing was ever started under it."""
        return self._first(sa.select(automation_attempts).where(_ATTEMPTS.id == attempt_id))

    def phase_events_after(self, attempt_id: str, after: int = 0) -> list[tuple[int, dict]]:
        """The attempt's phase events past event id `after`, as `(id, event)`, oldest first."""
        with self.store.connect() as conn:
            return read_phase_events(conn, attempt_phase_events.c.attempt_id, attempt_id, after)

    def get_last_attempt(self) -> AutomationAttempt | None:
        """Return the most recently started automation attempt."""
        return self._first(
            sa.select(automation_attempts)
            .order_by(_ATTEMPTS.started_at.desc(), _ATTEMPTS.seq.desc())
            .limit(1)
        )

    def get_last_daily_attempt(self) -> AutomationAttempt | None:
        """Return the most recent attempt that counts as a day's automation run.

        The daily timer reads it to decide whether today's run already happened. One that
        tried to make a film (running, completed or failed) counts, and so does a decision
        that nothing is worth a film today. A dry run, finished or still running, generated
        nothing; a cooldown skip (what most HTTP triggers get back), a chosen candidate that
        was no longer eligible and an attempt whose process died decided nothing about
        today. None of them cancels the timer.
        """
        running = sa.and_(
            _ATTEMPTS.outcome == AutoOutcome.RUNNING.value,
            sa.not_(_ATTEMPTS.reason.endswith(DRY_RUN_MARK)),
        )
        # A failure counts when it tried to make a film: a stale chosen candidate tried
        # nothing, and a process that died never got to finish today's try.
        failed = sa.and_(
            _ATTEMPTS.outcome == AutoOutcome.FAILED.value,
            sa.not_(_ATTEMPTS.reason.startswith(STALE_CANDIDATE_REASON)),
            sa.not_(_ATTEMPTS.reason.startswith(INTERRUPTED_REASON)),
        )
        ran = sa.or_(running, _ATTEMPTS.outcome == AutoOutcome.COMPLETED.value, failed)
        decided_nothing = sa.and_(
            _ATTEMPTS.outcome == AutoOutcome.SKIPPED.value,
            sa.or_(
                _ATTEMPTS.reason == NO_ELIGIBLE_CANDIDATES,
                _ATTEMPTS.reason.startswith(DECLINED_REASON),
            ),
        )
        return self._first(
            sa.select(automation_attempts)
            .where(sa.or_(ran, decided_nothing))
            .order_by(_ATTEMPTS.started_at.desc(), _ATTEMPTS.seq.desc())
            .limit(1)
        )

    def _first(self, query: sa.Select) -> AutomationAttempt | None:
        with self.store.connect() as conn:
            row = conn.execute(query).mappings().first()
        if not row:
            return None
        attempt = _row_to_attempt(row)
        # One attempt per call, so its events are one small read.
        events = [event for _, event in self.phase_events_after(attempt.id)]
        return replace(attempt, phase_events=events)

    def consecutive_failures_by_key(self) -> dict[str, FailureStreak]:
        """Failures per memory since it last completed, keyed by `memory_identity`.

        Read by candidate selection so a memory that cannot render stops being
        chosen every night. Only terminal failures count -- a SKIPPED attempt
        means the runner declined the candidate, which says nothing about
        whether it would have rendered. The exception is a period the child read
        and found nothing worth a film in: that candidate is marked declined.
        """
        query = (
            sa.select(
                _ATTEMPTS.memory_key, _ATTEMPTS.outcome, _ATTEMPTS.finished_at, _ATTEMPTS.reason
            )
            .where(
                _ATTEMPTS.memory_key.is_not(None),
                sa.or_(
                    _ATTEMPTS.outcome.in_([AutoOutcome.FAILED.value, AutoOutcome.COMPLETED.value]),
                    sa.and_(
                        _ATTEMPTS.outcome == AutoOutcome.SKIPPED.value,
                        _ATTEMPTS.reason.startswith(DECLINED_REASON),
                    ),
                ),
            )
            .order_by(_ATTEMPTS.started_at, _ATTEMPTS.seq)
        )
        with self.store.connect() as conn:
            rows = conn.execute(query).all()

        streaks: dict[str, FailureStreak] = {}
        for row in rows:
            key = memory_identity(row.memory_key)
            if row.outcome == AutoOutcome.COMPLETED.value:
                streaks.pop(key, None)
                continue
            previous = streaks.get(key)
            streaks[key] = FailureStreak(
                count=(previous.count if previous else 0) + 1,
                last_failed_at=from_db(row.finished_at),
                declined=row.outcome == AutoOutcome.SKIPPED.value,
            )
        return streaks
