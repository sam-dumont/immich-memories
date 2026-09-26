"""Run history: the records `immich-memories runs` prints, as JSON."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from immich_memories.config_loader import Config
from immich_memories.operations.auto_output import output_log_path
from immich_memories.operations.run_index import attempt_dir_for_run
from immich_memories.operations.storyboard import read_storyboard
from immich_memories.tracking import RunDatabase
from immich_memories.tracking.models import RunMetadata
from immich_memories.web.dependencies import current_config
from immich_memories.web.schemas import PhaseTiming, RunDetail, RunPage, RunSummary

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])

# Enough pictures for a card's strip; the whole cut is one request away.
_PREVIEW_SHOTS = 8


def _preview(config: Config, run_id: str) -> list[str]:
    attempt = attempt_dir_for_run(config.cache.cache_path, run_id)
    board = read_storyboard(attempt) if attempt else None
    return [shot.asset_id for shot in board.shots[:_PREVIEW_SHOTS]] if board else []


def _summary(config: Config, record: RunMetadata) -> RunSummary:
    return RunSummary(
        run_id=record.run_id,
        status=record.status,
        source=record.source,
        created_at=record.created_at,
        memory_type=record.memory_type,
        date_range_start=record.date_range_start,
        date_range_end=record.date_range_end,
        preview_asset_ids=_preview(config, record.run_id),
    )


@router.get("", response_model=RunPage)
def list_runs(
    config: Annotated[Config, Depends(current_config)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: Literal["completed", "failed", "running", "cancelled", "interrupted"] | None = None,
) -> RunPage:
    """Runs newest first, each with the first pictures its saved cut plays."""
    records = RunDatabase(config.cache.database_path).list_runs(
        limit=limit + 1, offset=offset, status=status
    )
    return RunPage(
        runs=[_summary(config, record) for record in records[:limit]],
        next_offset=offset + limit if len(records) > limit else None,
    )


def _child_output(config: Config, record: RunMetadata) -> Path | None:
    # `generate --automation-attempt-id` takes any string; only an id automation opened
    # addresses a transcript.
    if not record.automation_attempt_id:
        return None
    try:
        log = output_log_path(config.cache.cache_path, record.automation_attempt_id)
    except ValueError:
        return None
    return log if log.is_file() else None


def _record(config: Config, run_id: str) -> RunMetadata:
    record = RunDatabase(config.cache.database_path).get_run(run_id)
    if record is None:
        raise HTTPException(404, "Run not found. It may have been removed.")
    return record


@router.get("/{run_id}", response_model=RunDetail)
def read_run(run_id: str, config: Annotated[Config, Depends(current_config)]) -> RunDetail:
    """One run as `runs show` reads it: outcome, output, delivery, warnings and phase timings."""
    record = _record(config, run_id)
    summary = _summary(config, record)
    return RunDetail(
        **summary.model_dump(),
        completed_at=record.completed_at,
        output_path=record.output_path,
        delivery_status=record.delivery_status.value,
        warnings=record.warnings.copy(),
        phases=[
            PhaseTiming(
                name=phase.phase_name,
                seconds=phase.duration_seconds,
                errors=[str(error) for error in phase.errors],
            )
            for phase in record.phases
        ],
        clips_selected=record.clips_selected,
        has_cut=bool(summary.preview_asset_ids),
        child_output=_child_output(config, record) is not None,
    )


@router.get("/{run_id}/child-output", response_class=FileResponse)
def child_output(run_id: str, config: Annotated[Config, Depends(current_config)]) -> FileResponse:
    """The retained output of an automatic run, credentials already removed when it was kept."""
    log = _child_output(config, _record(config, run_id))
    if log is None:
        raise HTTPException(404, "No child output was retained for this run.")
    return FileResponse(log, media_type="text/plain", filename=f"{run_id}-output.log")
