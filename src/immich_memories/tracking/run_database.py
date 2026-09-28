"""Pipeline run history, kept in the store.

Row conversion lives in run_database_rows.py; the lifecycle transition errors in
run_lifecycle_errors.py. Every lifecycle transition is one conditional UPDATE, so two
processes racing on the same run cannot both win it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn

import sqlalchemy as sa
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from immich_memories.db import Store, open_store, to_db
from immich_memories.db.tables import automation_attempts, phase_stats, pipeline_runs
from immich_memories.operations.phases import PhaseEvent
from immich_memories.tracking.models import DeliveryStatus, PhaseStats, RunMetadata
from immich_memories.tracking.phase_rows import advance_phase
from immich_memories.tracking.run_database_rows import (
    phase_stats_to_row,
    row_to_phase_stats,
    row_to_run,
    run_to_row,
)
from immich_memories.tracking.run_lifecycle_errors import (
    DuplicateRunError,
    raise_invalid_artifact_transition,
    raise_invalid_delivery_transition,
)

logger = logging.getLogger(__name__)

# SQLite's default limit on bound variables is 999; stay under it for `IN (...)`.
_CHUNK = 900

_RUNS = pipeline_runs.c
_COMPLETION_ORDER = (
    sa.func.coalesce(_RUNS.completed_at, _RUNS.created_at).desc(),
    _RUNS.created_at.desc(),
    _RUNS.run_id.desc(),
)


def _chunks(values: Sequence[str]) -> Iterable[Sequence[str]]:
    for start in range(0, len(values), _CHUNK):
        yield values[start : start + _CHUNK]


class RunDatabase:
    """Pipeline run history: every run, its phase timings, and its delivery lifecycle."""

    def __init__(self, store: Store | None = None):
        self.store = store or open_store()

    def save_run(self, run: RunMetadata) -> None:
        """Insert a new run without replacing an existing authoritative identity."""
        try:
            with self.store.begin() as conn:
                conn.execute(sa.insert(pipeline_runs), [run_to_row(run)])
        except IntegrityError as error:
            raise DuplicateRunError(f"Pipeline run already exists: {run.run_id}") from error

    def update_operational_phase(self, run_id: str, event: PhaseEvent) -> bool:
        """Persist a monotonic run phase and mirror its exact automation attempt."""
        with self.store.begin() as conn:
            advanced = advance_phase(conn, pipeline_runs, _RUNS.run_id, run_id, event)
            if advanced is None:
                raise KeyError(f"Unknown pipeline run: {run_id}")
            if not advanced:
                return False
            attempt_id = conn.execute(
                sa.select(_RUNS.automation_attempt_id).where(_RUNS.run_id == run_id)
            ).scalar()
            if attempt_id:
                advance_phase(
                    conn, automation_attempts, automation_attempts.c.id, attempt_id, event
                )
        return True

    def save_phase_stats(self, run_id: str, stats: PhaseStats) -> None:
        """Save phase timing statistics.

        A run that no longer exists (deleted mid-run) loses its phase stats with a
        warning: they are observability data, and losing them is acceptable.
        """
        try:
            with self.store.begin() as conn:
                conn.execute(sa.insert(phase_stats), [phase_stats_to_row(run_id, stats)])
        except IntegrityError:
            logger.warning(
                "Phase stats lost for '%s' — run_id '%s' may no longer exist in database",
                stats.phase_name,
                run_id,
            )

    def get_run(self, run_id: str) -> RunMetadata | None:
        """Get a single run by ID, with its phase timings."""
        runs = self._select_runs(sa.select(pipeline_runs).where(_RUNS.run_id == run_id))
        return runs[0] if runs else None

    def delete_run(self, run_id: str) -> bool:
        """Delete a run and its stats."""
        with self.store.begin() as conn:
            result = conn.execute(sa.delete(pipeline_runs).where(_RUNS.run_id == run_id))
        return result.rowcount > 0

    def update_run_status(
        self,
        run_id: str,
        status: str,
        completed_at: datetime | None = None,
        output_path: str | None = None,
        output_size_bytes: int | None = None,
        output_duration_seconds: float | None = None,
        clips_analyzed: int | None = None,
        clips_selected: int | None = None,
        errors_count: int | None = None,
        delivery_album: str | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        """Update run status and whichever other fields were given."""
        given = {
            "completed_at": to_db(completed_at),
            "output_path": output_path,
            "output_size_bytes": output_size_bytes,
            "output_duration_seconds": output_duration_seconds,
            "clips_analyzed": clips_analyzed,
            "clips_selected": clips_selected,
            "errors_count": errors_count,
            "delivery_album": delivery_album,
            "warnings": warnings,
        }
        values = {"status": status} | {k: v for k, v in given.items() if v is not None}
        with self.store.begin() as conn:
            conn.execute(sa.update(pipeline_runs).where(_RUNS.run_id == run_id).values(values))

    def _transition(
        self,
        run_id: str,
        where: Sequence[sa.ColumnElement[bool]],
        values: dict[str, Any],
        refuse: Callable[[Connection, str], NoReturn],
    ) -> RunMetadata:
        """Apply one guarded lifecycle UPDATE, or name the precondition it missed."""
        with self.store.begin() as conn:
            result = conn.execute(
                sa.update(pipeline_runs).where(_RUNS.run_id == run_id, *where).values(values)
            )
            if result.rowcount != 1:
                refuse(conn, run_id)
        saved = self.get_run(run_id)
        if saved is None:  # pragma: no cover - the UPDATE just matched this row
            raise KeyError(f"Unknown pipeline run: {run_id}")
        return saved

    def mark_delivery_abandoned(self, run_id: str, error: str) -> RunMetadata:
        """Stop retrying a delivery that has used up its attempts.

        The artifact stays completed and on disk; only its delivery gives up.
        Leaving it pending would consume every nightly wake forever, because the
        runner retries a pending delivery before it considers generating.
        """
        return self._transition(
            run_id,
            [_RUNS.status == "completed"],
            {"delivery_status": DeliveryStatus.ABANDONED.value, "delivery_error": error},
            raise_invalid_delivery_transition,
        )

    def mark_delivery_pending(
        self,
        run_id: str,
        error: str,
        *,
        attempted: bool = True,
    ) -> RunMetadata:
        """Record one failed delivery call without changing artifact completion."""
        return self._transition(
            run_id,
            [_RUNS.status == "completed"],
            {
                "delivery_status": DeliveryStatus.PENDING.value,
                "delivery_attempts": _RUNS.delivery_attempts + int(attempted),
                "delivery_error": error,
                "immich_asset_id": None,
            },
            raise_invalid_delivery_transition,
        )

    def complete_artifact(
        self,
        run_id: str,
        *,
        completed_at: datetime,
        output_path: str,
        output_size_bytes: int,
        output_duration_seconds: float,
        delivery_requested: bool,
        delivery_album: str | None,
        warnings: list[str],
        clips_analyzed: int,
        clips_selected: int,
        errors_count: int,
        llm_metrics: dict | None = None,
    ) -> RunMetadata:
        """Atomically commit artifact facts and its initial delivery lifecycle."""
        delivery_status = (
            DeliveryStatus.PENDING if delivery_requested else DeliveryStatus.NOT_REQUESTED
        )
        return self._transition(
            run_id,
            [_RUNS.status == "running"],
            {
                "status": "completed",
                "completed_at": to_db(completed_at),
                "output_path": output_path,
                "output_size_bytes": output_size_bytes,
                "output_duration_seconds": output_duration_seconds,
                "clips_analyzed": clips_analyzed,
                "clips_selected": clips_selected,
                "errors_count": errors_count,
                "delivery_status": delivery_status.value,
                "delivery_attempts": 0,
                "delivery_error": None,
                "immich_asset_id": None,
                "delivery_album": delivery_album,
                "warnings": warnings.copy(),
                "llm_metrics": llm_metrics or None,
            },
            raise_invalid_artifact_transition,
        )

    def mark_delivered(self, run_id: str, asset_id: str) -> RunMetadata:
        """Record one successful delivery call without changing artifact completion."""
        normalized_asset_id = asset_id.strip()
        if not normalized_asset_id:
            raise ValueError("Immich delivery requires a nonempty asset ID")
        return self._transition(
            run_id,
            [_RUNS.status == "completed", _RUNS.delivery_status == DeliveryStatus.PENDING.value],
            {
                "delivery_status": DeliveryStatus.DELIVERED.value,
                "delivery_attempts": _RUNS.delivery_attempts + 1,
                "delivery_error": None,
                "immich_asset_id": normalized_asset_id,
            },
            raise_invalid_delivery_transition,
        )

    def mark_stale_runs_as_interrupted(self) -> int:
        """Mark any 'running' runs as 'interrupted' (startup cleanup)."""
        with self.store.begin() as conn:
            count = conn.execute(
                sa.update(pipeline_runs)
                .where(_RUNS.status == "running")
                .values(status="interrupted")
            ).rowcount
        if count > 0:
            logger.info(f"Marked {count} stale run(s) as interrupted")
        return count

    def _pending_deliveries(self, source: str) -> sa.Select:
        return sa.select(_RUNS.run_id, _RUNS.output_path).where(
            _RUNS.status == "completed",
            _RUNS.delivery_status == DeliveryStatus.PENDING.value,
            _RUNS.output_path.is_not(None),
            _RUNS.source == source,
        )

    def get_oldest_pending_delivery(self, source: str) -> RunMetadata | None:
        """Return the oldest completed pending delivery for one source."""
        query = self._pending_deliveries(source).order_by(
            sa.func.coalesce(_RUNS.completed_at, _RUNS.created_at),
            _RUNS.created_at,
            _RUNS.run_id,
        )
        with self.store.connect() as conn:
            rows = conn.execute(query).all()
        for row in rows:
            if Path(row.output_path).is_file():
                return self.get_run(row.run_id)
            logger.warning(
                "Pending delivery run '%s' cannot be retried because its output file "
                "is missing or not a regular file: %s",
                row.run_id,
                row.output_path,
            )
        return None

    def count_pending_deliveries(self, source: str = "auto") -> int:
        """Count durable pending deliveries without hiding missing artifacts."""
        query = sa.select(sa.func.count()).select_from(self._pending_deliveries(source).subquery())
        with self.store.connect() as conn:
            return int(conn.execute(query).scalar_one())

    def record_llm_metrics(self, run_id: str, metrics: dict) -> None:
        """Store what the run spent on the model."""
        if not metrics:
            return
        self._set(run_id, llm_metrics=metrics.copy())

    def record_title_source(self, run_id: str, source: str) -> None:
        """Store which source produced the run's opening title."""
        self._set(run_id, title_source=source)

    def _set(self, run_id: str, **values: Any) -> None:
        with self.store.begin() as conn:
            conn.execute(sa.update(pipeline_runs).where(_RUNS.run_id == run_id).values(values))

    def _phases_of(self, run_ids: Sequence[str]) -> dict[str, list[PhaseStats]]:
        found: dict[str, list[PhaseStats]] = {}
        with self.store.connect() as conn:
            for chunk in _chunks(run_ids):
                rows = conn.execute(
                    sa.select(phase_stats)
                    .where(phase_stats.c.run_id.in_(chunk))
                    .order_by(phase_stats.c.started_at, phase_stats.c.id)
                ).mappings()
                for row in rows:
                    found.setdefault(row["run_id"], []).append(row_to_phase_stats(row))
        return found

    def _select_runs(self, query: sa.Select, *, with_phases: bool = True) -> list[RunMetadata]:
        with self.store.connect() as conn:
            runs = [row_to_run(row) for row in conn.execute(query).mappings()]
        if with_phases and runs:
            phases = self._phases_of([run.run_id for run in runs])
            for run in runs:
                run.phases = phases.get(run.run_id, [])
        return runs

    def list_runs(
        self,
        limit: int = 50,
        offset: int = 0,
        person_name: str | None = None,
        status: str | None = None,
        source: str | None = None,
        order_by_completion: bool = False,
    ) -> list[RunMetadata]:
        """List runs with optional filtering and explicit completion ordering."""
        if order_by_completion and status != "completed":
            msg = "order_by_completion requires status='completed'"
            raise ValueError(msg)
        query = sa.select(pipeline_runs)
        if person_name:
            query = query.where(_RUNS.person_name == person_name)
        if status:
            query = query.where(_RUNS.status == status)
        if source is not None:
            query = query.where(_RUNS.source == source)
        order = _COMPLETION_ORDER if order_by_completion else (_RUNS.created_at.desc(),)
        return self._select_runs(query.order_by(*order).limit(limit).offset(offset))

    def get_aggregate_stats(self) -> dict:
        """Get aggregate statistics across all runs."""
        per_run = (
            sa.select(sa.func.sum(phase_stats.c.duration_seconds).label("total"))
            .join(pipeline_runs, phase_stats.c.run_id == _RUNS.run_id)
            .where(_RUNS.status == "completed")
            .group_by(phase_stats.c.run_id)
            .subquery()
        )
        with self.store.connect() as conn:
            totals = conn.execute(
                sa.select(
                    sa.func.count().label("runs"),
                    sa.func.count().filter(_RUNS.status == "completed").label("completed"),
                    sa.func.count().filter(_RUNS.status == "failed").label("failed"),
                    sa.func.coalesce(sa.func.sum(_RUNS.output_duration_seconds), 0).label("out"),
                    sa.func.coalesce(sa.func.sum(_RUNS.clips_selected), 0).label("clips"),
                )
            ).one()
            processing: float = conn.execute(
                sa.select(sa.func.coalesce(sa.func.sum(phase_stats.c.duration_seconds), 0))
            ).scalar_one()
            average = conn.execute(sa.select(sa.func.avg(per_run.c.total))).scalar()
        return {
            "total_runs": totals.runs,
            "completed_runs": totals.completed,
            "failed_runs": totals.failed,
            "total_output_seconds": totals.out,
            "total_processing_seconds": processing,
            "avg_run_seconds": float(average or 0.0) if totals.completed > 0 else 0.0,
            "avg_clips": totals.clips / totals.runs if totals.runs > 0 else 0.0,
            "total_clips": totals.clips,
        }

    def get_last_run_of_type(
        self,
        memory_type: str,
        source: str | None = None,
    ) -> RunMetadata | None:
        """Get the most recent completed run of a type, optionally scoped by source."""
        query = sa.select(pipeline_runs).where(
            _RUNS.memory_type == memory_type, _RUNS.status == "completed"
        )
        if source is not None:
            query = query.where(_RUNS.source == source)
        runs = self._select_runs(query.order_by(*_COMPLETION_ORDER).limit(1), with_phases=False)
        return runs[0] if runs else None

    def get_generated_memory_keys(self) -> set[str]:
        """Get all memory_keys a finished film exists for.

        A cut recorded without rendering (`generate --no-render`, the web client's review) has
        no output yet: the memory is not made until a render of it is.
        """
        query = (
            sa.select(_RUNS.memory_key)
            .where(
                _RUNS.status == "completed",
                _RUNS.memory_key.is_not(None),
                _RUNS.output_path.is_not(None),
                _RUNS.output_path != "",
            )
            .distinct()
        )
        with self.store.connect() as conn:
            return set(conn.execute(query).scalars())

    def delivered_asset_ids(self) -> frozenset[str]:
        """Every Immich asset id this install recorded when it uploaded a finished film."""
        query = sa.select(_RUNS.immich_asset_id).where(
            _RUNS.immich_asset_id.is_not(None), sa.func.trim(_RUNS.immich_asset_id) != ""
        )
        with self.store.connect() as conn:
            return frozenset(conn.execute(query).scalars())

    def get_run_by_automation_attempt(self, automation_attempt_id: str) -> RunMetadata | None:
        """Find the newest run of any status that one automation attempt started.

        The completed-only lookup answers delivery; this one answers "where did
        that attempt end up", which is the question a failed attempt raises.
        """
        query = (
            sa.select(pipeline_runs)
            .where(_RUNS.automation_attempt_id == automation_attempt_id)
            .order_by(_RUNS.created_at.desc(), _RUNS.run_id.desc())
            .limit(1)
        )
        runs = self._select_runs(query, with_phases=False)
        return runs[0] if runs else None

    def get_completed_run_by_automation_attempt(
        self,
        automation_attempt_id: str,
        *,
        memory_key: str,
    ) -> RunMetadata | None:
        """Find the completed auto run created by one exact automation attempt."""
        query = (
            sa.select(pipeline_runs)
            .where(
                _RUNS.automation_attempt_id == automation_attempt_id,
                _RUNS.memory_key == memory_key,
                _RUNS.source == "auto",
                _RUNS.status == "completed",
            )
            .order_by(_RUNS.created_at.desc())
            .limit(2)
        )
        runs = self._select_runs(query, with_phases=False)
        if len(runs) > 1:
            raise RuntimeError(
                f"Multiple completed auto runs matched automation attempt {automation_attempt_id}"
            )
        return runs[0] if runs else None
