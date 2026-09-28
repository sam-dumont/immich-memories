"""Pipeline run history as store rows, and back."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from immich_memories.db import from_db, to_db
from immich_memories.operations.phases import OperationalPhase
from immich_memories.tracking.models import (
    DeliveryStatus,
    PhaseStats,
    RunMetadata,
    SystemInfo,
    normalize_memory_people,
)


def _iso_date(value: date | None) -> str | None:
    return value.isoformat() if value else None


def run_to_row(run: RunMetadata) -> dict[str, Any]:
    """Every column of a new `pipeline_runs` row."""
    return {
        "run_id": run.run_id,
        "created_at": to_db(run.created_at),
        "completed_at": to_db(run.completed_at),
        "status": run.status,
        "memory_type": run.memory_type,
        "memory_key": run.memory_key,
        "memory_category": run.memory_category,
        "memory_people": list(normalize_memory_people(run.memory_people)),
        "source": run.source,
        "automation_attempt_id": run.automation_attempt_id,
        "last_phase": run.last_phase.value if run.last_phase else None,
        "phase_events": run.phase_events.copy(),
        "person_name": run.person_name,
        "person_id": run.person_id,
        "date_range_start": _iso_date(run.date_range_start),
        "date_range_end": _iso_date(run.date_range_end),
        "target_duration_seconds": run.target_duration_seconds,
        "output_path": run.output_path,
        "output_size_bytes": run.output_size_bytes,
        "output_duration_seconds": run.output_duration_seconds,
        "clips_analyzed": run.clips_analyzed,
        "clips_selected": run.clips_selected,
        "errors_count": run.errors_count,
        "system_info": run.system_info.to_dict() if run.system_info else None,
        "delivery_status": run.delivery_status.value,
        "delivery_attempts": run.delivery_attempts,
        "delivery_error": run.delivery_error,
        "immich_asset_id": run.immich_asset_id,
        "delivery_album": run.delivery_album,
        "warnings": run.warnings.copy(),
        "llm_metrics": run.llm_metrics or None,
        "title_source": run.title_source,
    }


def row_to_run(row: Mapping[Any, Any]) -> RunMetadata:
    """A `pipeline_runs` row as the run it records (phases are attached by the caller)."""
    created_at = from_db(row["created_at"])
    assert created_at is not None
    return RunMetadata(
        run_id=row["run_id"],
        created_at=created_at,
        completed_at=from_db(row["completed_at"]),
        status=row["status"],
        memory_type=row["memory_type"],
        memory_key=row["memory_key"],
        memory_category=row["memory_category"],
        memory_people=tuple(row["memory_people"] or ()),
        source=row["source"],
        automation_attempt_id=row["automation_attempt_id"],
        phase_events=list(row["phase_events"] or []),
        last_phase=OperationalPhase(row["last_phase"]) if row["last_phase"] else None,
        person_name=row["person_name"],
        person_id=row["person_id"],
        date_range_start=(
            date.fromisoformat(row["date_range_start"]) if row["date_range_start"] else None
        ),
        date_range_end=(
            date.fromisoformat(row["date_range_end"]) if row["date_range_end"] else None
        ),
        target_duration_seconds=(
            row["target_duration_seconds"] if row["target_duration_seconds"] is not None else 600
        ),
        output_path=row["output_path"],
        output_size_bytes=row["output_size_bytes"] or 0,
        output_duration_seconds=row["output_duration_seconds"] or 0.0,
        delivery_status=DeliveryStatus(row["delivery_status"]),
        delivery_attempts=row["delivery_attempts"] or 0,
        delivery_error=row["delivery_error"],
        immich_asset_id=row["immich_asset_id"],
        delivery_album=row["delivery_album"],
        warnings=list(row["warnings"] or []),
        llm_metrics=dict(row["llm_metrics"] or {}),
        title_source=row["title_source"],
        clips_analyzed=row["clips_analyzed"] or 0,
        clips_selected=row["clips_selected"] or 0,
        errors_count=row["errors_count"] or 0,
        system_info=SystemInfo.from_dict(row["system_info"]) if row["system_info"] else None,
    )


def phase_stats_to_row(run_id: str, stats: PhaseStats) -> dict[str, Any]:
    """One `phase_stats` row for a finished phase of `run_id`."""
    return {
        "run_id": run_id,
        "phase_name": stats.phase_name,
        "started_at": to_db(stats.started_at),
        "completed_at": to_db(stats.completed_at),
        "duration_seconds": stats.duration_seconds,
        "items_processed": stats.items_processed,
        "items_total": stats.items_total,
        "errors": stats.errors.copy() if stats.errors else None,
        "extra_metrics": stats.extra_metrics.copy() if stats.extra_metrics else None,
    }


def row_to_phase_stats(row: Mapping[Any, Any]) -> PhaseStats:
    """A `phase_stats` row as the phase timing it records."""
    started_at = from_db(row["started_at"])
    assert started_at is not None
    return PhaseStats(
        phase_name=row["phase_name"],
        started_at=started_at,
        completed_at=from_db(row["completed_at"]),
        duration_seconds=row["duration_seconds"] or 0.0,
        items_processed=row["items_processed"] or 0,
        items_total=row["items_total"] or 0,
        errors=list(row["errors"] or []),
        extra_metrics=dict(row["extra_metrics"] or {}),
    )
