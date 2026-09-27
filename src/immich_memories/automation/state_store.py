"""Automation attempts, kept in the store: what the nightly runner tried and how it ended."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import sqlalchemy as sa

from immich_memories.automation.models import AutomationAttempt, AutoOutcome
from immich_memories.db import Store, from_db, open_store, to_db
from immich_memories.db.tables import automation_attempts
from immich_memories.operations.phases import OperationalPhase, PhaseEvent
from immich_memories.tracking.phase_rows import advance_phase

logger = logging.getLogger(__name__)

_ATTEMPTS = automation_attempts.c


@dataclass(frozen=True)
class FailureStreak:
    """How many times a memory key has failed since it last succeeded."""

    count: int
    last_failed_at: datetime | None


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
        phase_events=list(row["phase_events"] or []),
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
            seq = conn.execute(sa.select(sa.func.coalesce(sa.func.max(_ATTEMPTS.seq), 0))).scalar()
            conn.execute(
                sa.insert(automation_attempts),
                [
                    {
                        "id": attempt.id,
                        "seq": int(seq or 0) + 1,
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
            advanced = advance_phase(conn, automation_attempts, _ATTEMPTS.id, attempt_id, event)
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

    def get_attempt(self, attempt_id: str) -> AutomationAttempt | None:
        """Return one attempt by id, or None when nothing was ever started under it."""
        return self._first(sa.select(automation_attempts).where(_ATTEMPTS.id == attempt_id))

    def get_last_attempt(self) -> AutomationAttempt | None:
        """Return the most recently started automation attempt."""
        return self._first(
            sa.select(automation_attempts)
            .order_by(_ATTEMPTS.started_at.desc(), _ATTEMPTS.seq.desc())
            .limit(1)
        )

    def _first(self, query: sa.Select) -> AutomationAttempt | None:
        with self.store.connect() as conn:
            row = conn.execute(query).mappings().first()
        return _row_to_attempt(row) if row else None

    def consecutive_failures_by_key(self) -> dict[str, FailureStreak]:
        """Failures per memory key since that key last completed.

        Read by candidate selection so a memory that cannot render stops being
        chosen every night. Only terminal failures count -- a SKIPPED attempt
        means the runner declined the candidate, which says nothing about
        whether it would have rendered.
        """
        query = (
            sa.select(_ATTEMPTS.memory_key, _ATTEMPTS.outcome, _ATTEMPTS.finished_at)
            .where(
                _ATTEMPTS.memory_key.is_not(None),
                _ATTEMPTS.outcome.in_([AutoOutcome.FAILED.value, AutoOutcome.COMPLETED.value]),
            )
            .order_by(_ATTEMPTS.started_at, _ATTEMPTS.seq)
        )
        with self.store.connect() as conn:
            rows = conn.execute(query).all()

        streaks: dict[str, FailureStreak] = {}
        for row in rows:
            key: str = row.memory_key
            if row.outcome == AutoOutcome.COMPLETED.value:
                streaks.pop(key, None)
                continue
            previous = streaks.get(key)
            streaks[key] = FailureStreak(
                count=(previous.count if previous else 0) + 1,
                last_failed_at=from_db(row.finished_at),
            )
        return streaks
