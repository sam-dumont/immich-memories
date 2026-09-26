"""Run history: the records `immich-memories runs` prints, as JSON."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from immich_memories.config_loader import Config
from immich_memories.operations.run_index import attempt_dir_for_run
from immich_memories.operations.storyboard import read_storyboard
from immich_memories.tracking import RunDatabase
from immich_memories.tracking.models import RunMetadata
from immich_memories.web.dependencies import current_config
from immich_memories.web.schemas import RunPage, RunSummary

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
