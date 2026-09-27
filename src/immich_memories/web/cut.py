"""One saved cut for the review workspace: the storyboard, the rules' path and the model's record."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from immich_memories.analysis.selection_trace import Trace
from immich_memories.config_loader import Config
from immich_memories.operations.candidate_fates import CandidateFates
from immich_memories.operations.cut_review import model_polish_ran, read_cut_decisions
from immich_memories.operations.reader_words import stage_words
from immich_memories.operations.run_index import attempt_dir_for_run
from immich_memories.operations.storyboard import (
    Shot,
    moment_alternatives,
    read_storyboard,
    source_intervals,
)
from immich_memories.web.dependencies import current_config
from immich_memories.web.schemas import Alternative, Cut, CutShot, ModelDecision, SelectionPath

router = APIRouter(prefix="/api/v1/runs", tags=["cut"])


def _selection(trace: Trace | None, asset_id: str) -> SelectionPath | None:
    if trace is None:
        return None
    story = trace.story_of(asset_id)
    return SelectionPath(
        facts=story.facts,
        passed=[stage_words(stage) for stage in story.survived],
        left_out_at=stage_words(story.dropped_at) if story.dropped_at else None,
        left_out_because=story.reason,
        kept_at=stage_words(story.admitted_at) if story.admitted_at else None,
    )


@dataclass(frozen=True)
class _Evidence:
    """Everything the attempt recorded that the review explains a shot with."""

    decisions: dict[str, dict[str, str | int]]
    intervals: dict[str, tuple[float, float]]
    fates: CandidateFates
    siblings: dict[str, list[str]]

    def facts(self, asset_id: str) -> str:
        return self.fates.trace.clips.get(asset_id, "") if self.fates.trace else ""


def _shot(position: int, shot: Shot, evidence: _Evidence) -> CutShot:
    decision = evidence.decisions.get(shot.asset_id)
    return CutShot(
        asset_id=shot.asset_id,
        position=position,
        start=shot.start,
        seconds=shot.seconds,
        taken=shot.taken,
        day=shot.day,
        new_day=shot.new_day,
        chapter=shot.chapter,
        story_key=shot.story_key,
        story_title=shot.story_title,
        moment=shot.moment,
        reason=shot.reason,
        motion=shot.motion,
        source_interval=evidence.intervals.get(shot.asset_id) if shot.motion else None,
        selection=_selection(evidence.fates.trace, shot.asset_id),
        model=ModelDecision.model_validate(decision) if decision else None,
        alternatives=[
            Alternative(
                asset_id=asset, facts=evidence.facts(asset), fate=evidence.fates.describe(asset)
            )
            for asset in evidence.siblings.get(shot.asset_id, ())
        ],
    )


@router.get("/{run_id}/cut", response_model=Cut)
def read_cut(run_id: str, config: Annotated[Config, Depends(current_config)]) -> Cut:
    """The cut in the order it plays, each shot with every reason the run recorded for it."""
    attempt = attempt_dir_for_run(config.cache.cache_path, run_id)
    board = read_storyboard(attempt) if attempt else None
    if attempt is None or board is None:
        raise HTTPException(404, "This run left no saved cut.")
    evidence = _Evidence(
        decisions=read_cut_decisions(attempt),
        intervals=source_intervals(attempt),
        fates=CandidateFates.read(attempt),
        siblings=moment_alternatives(attempt),
    )
    return Cut(
        run_id=run_id,
        thesis=board.thesis,
        content_seconds=board.total_seconds,
        film_seconds=board.film_seconds,
        model_polish=model_polish_ran(attempt),
        shots=[_shot(index, shot, evidence) for index, shot in enumerate(board.shots, 1)],
    )
