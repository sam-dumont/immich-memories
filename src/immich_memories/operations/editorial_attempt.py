"""Durable, isolated selection attempts with a process-owned liveness lease."""

from __future__ import annotations

import json
from collections.abc import Mapping
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from immich_memories.analysis.llm_metrics import LLMCounters, collecting
from immich_memories.analysis.llm_usage_record import write_llm_usage
from immich_memories.db.leases import Lease
from immich_memories.operations.cancellation import PipelineCancelled
from immich_memories.operations.cut_progress import ANALYSIS_PHASE, StageClock, StageUpdate
from immich_memories.security import write_secret_file

if TYPE_CHECKING:
    from immich_memories.db import Store

_FIRST_STAGE = StageUpdate("Preparing editorial evidence", ANALYSIS_PHASE)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class EditorialAttempt:
    """Keep each run's artifacts separate while semantic caches remain reusable.

    The lease is released by the OS (or, on a PostgreSQL store, by the server when the
    holder's connection drops) even after a crash. A reader can distinguish an interrupted
    run from a slow live run without guessing from its age or PID.
    """

    def __init__(self, root: Path, *, request: dict[str, Any], store: Store | None = None) -> None:
        self.root = Path(root)
        self.attempt_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:12]
        self.directory = self.root / "attempts" / self.attempt_id
        self.record: dict[str, Any] = {
            "schema": "editorial-attempt-v1",
            "attempt_id": self.attempt_id,
            "status": "running",
            "started_at": _now(),
            "stage": _FIRST_STAGE.stage_label,
            "progress": _FIRST_STAGE.as_record(),
            "request": request,
            "restart": "Run the same request; completed exact judgments remain reusable.",
        }
        self._lease = _attempt_lease(self.directory, self.attempt_id, store)
        self._stage_clock = StageClock()
        from immich_memories.tracking.run_observations import current_tracker
        from immich_memories.tracking.span_progress import SpanPlan
        from immich_memories.tracking.span_store import SpanStore

        tracker = current_tracker()
        if tracker is not None and tracker.current_run is not None:
            history = SpanStore(tracker.db.store).latest(
                tracker.current_run.source, prefix="stage."
            )
            if history:
                self._stage_clock = StageClock(
                    plan=SpanPlan(
                        [span for span in history.spans if span.name.startswith("stage.")],
                        items=len(request.get("requested_assets", [])),
                    )
                )
        self._usage_scope = ExitStack()
        self._usage: LLMCounters | None = None

    def __enter__(self) -> EditorialAttempt:
        self.directory.mkdir(parents=True, mode=0o700)
        self._lease.acquire(wait=True)
        try:
            self._usage = self._usage_scope.enter_context(collecting())
            self._save()
            from immich_memories.operations.run_index import record_run_attempt
            from immich_memories.tracking.run_observations import current_tracker

            if tracker := current_tracker():
                record_run_attempt(tracker.run_id, self.directory, "", store=tracker.db.store)
            write_secret_file(
                self.root / "latest-attempt.private.json",
                json.dumps({"attempt_id": self.attempt_id, "directory": str(self.directory)}),
            )
        except BaseException:
            self._usage_scope.close()
            self._lease.release()
            raise
        return self

    def stage(self, update: StageUpdate | str) -> StageUpdate:
        """Record where the run is: the sentence for a row, the numbers for a bar."""
        if isinstance(update, str):
            update = StageUpdate(update)
        previous = StageUpdate.from_record(self.record["progress"])
        if previous and previous.identity == update.identity and previous.done == update.done:
            return previous  # The lease proves liveness; no disk heartbeat needed.
        update = self._stage_clock.measure(update)
        self.record["stage"] = update.stage_label
        self.record["progress"] = update.as_record()
        self._save()
        return update

    def complete(
        self,
        *,
        selected: int,
        outcome: str = "complete",
        duration_realization: dict | None = None,
        calls_by_stage: Mapping[str, Any] | None = None,
    ) -> None:
        self.record.update(status="complete", outcome=outcome, selected_carriers=selected)
        if duration_realization is not None:
            self.record["duration_realization"] = duration_realization
        if calls_by_stage is not None:
            self.record["calls_by_stage"] = dict(calls_by_stage)

    def _save(self) -> None:
        write_llm_usage(self.directory, self._usage)
        self.record["updated_at"] = _now()
        write_secret_file(
            self.directory / "status.private.json",
            json.dumps(self.record, ensure_ascii=False, indent=2),
        )

    def __exit__(self, _exc_type, exc, traceback) -> None:
        self._stage_clock.finish()
        try:
            if exc is not None:
                self.record["status"] = (
                    "cancelled"
                    if isinstance(exc, (PipelineCancelled, KeyboardInterrupt))
                    else "failed"
                )
                self.record["error_type"] = type(exc).__name__
            elif self.record["status"] == "running":
                self.record["status"] = "incomplete"
            self.record["finished_at"] = _now()
            self._save()
        finally:
            self._usage_scope.close()
            self._lease.release()


def _attempt_lease(directory: Path, attempt_id: str, store: Store | None) -> Lease:
    return Lease(f"editorial-attempt:{attempt_id}", directory / ".lease", store)


def read_editorial_attempt(directory: Path, store: Store | None = None) -> dict[str, Any]:
    """Read truthful liveness without changing an attempt's historical record."""
    record = json.loads((directory / "status.private.json").read_text())
    if record.get("status") != "running":
        return record
    if _attempt_lease(directory, record["attempt_id"], store).held_elsewhere():
        return record
    return record | {
        "status": "interrupted",
        "reason": "Planning process no longer owns its lease",
    }


def window_origin_note(directory: Path) -> str:
    """How a run came by a window nobody typed, or nothing when the dates were asked for."""
    try:
        request = json.loads((directory / "status.private.json").read_text()).get("request")
    except (OSError, ValueError):
        return ""
    origin = request.get("window_origin") if isinstance(request, dict) else None
    return f"Window: nobody typed one — {origin}" if origin else ""
