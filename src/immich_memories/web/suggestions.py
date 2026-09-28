"""Suggestions: what `auto suggest` would make next, and running one as `auto run` would."""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from immich_memories.automation.models import AutoOutcome
from immich_memories.automation.runner import AutomationAlreadyRunningError, AutoRunner
from immich_memories.automation.state_store import AutomationStateStore
from immich_memories.config_loader import Config
from immich_memories.db import open_store
from immich_memories.tracking import RunDatabase
from immich_memories.web.answer_cache import AnswerCache, Cached
from immich_memories.web.dependencies import answers, current_config

router = APIRouter(prefix="/api/v1", tags=["suggestions"])

# The attempt's reason, so a run somebody clicked for is not read as a nightly wake.
SUGGESTION_REASON = "web suggestion"


class Suggestion(BaseModel):
    memory_key: str
    memory_type: str
    category: str
    reason: str
    person_names: list[str]
    date_range_start: str
    date_range_end: str
    asset_count: int


class Skipped(BaseModel):
    label: str
    rule: str


class Suggestions(BaseModel):
    candidates: list[Suggestion]
    skipped: list[Skipped]
    error: str | None
    # When this list was worked out, and whether a fresher one is being worked out now.
    computed_at: datetime | None = None
    refreshing: bool = False


class RunSuggestion(BaseModel):
    memory_key: str
    dry_run: bool = False


class AttemptView(BaseModel):
    id: str
    outcome: str
    phase: str | None
    reason: str
    run_id: str | None


def automation(config: Annotated[Config, Depends(current_config)]) -> Any:
    """The runner the scheduler, `auto run` and the HTTP trigger share."""
    return AutoRunner(config)


def _discover(runner: Any) -> Suggestions:
    found = runner.suggest(limit=20) or []
    skipped = [
        Skipped(label=item.candidate.reason, rule=item.rule)
        for item in runner.last_variety_decision.rejected
    ] + [Skipped(label=key, rule=reason) for key, reason in runner.last_backoff_skips.items()]
    return Suggestions(
        candidates=[
            Suggestion(
                memory_key=c.memory_key,
                memory_type=c.memory_type,
                category=c.category.value,
                reason=c.reason,
                person_names=list(c.person_names),
                date_range_start=c.date_range_start.isoformat(),
                date_range_end=c.date_range_end.isoformat(),
                asset_count=c.asset_count,
            )
            for c in found
        ],
        skipped=skipped,
        error=runner.last_suggest_status.error,
    )


def suggestions_answer(cache: AnswerCache, runner: Any, *, refresh: bool = False) -> Cached:
    """The last discovery from the answer cache, run again behind the page when due."""
    return cache.read(
        "suggestions", lambda: _discover(runner).model_dump(mode="json"), refresh=refresh
    )


@router.get("/suggestions", response_model=Suggestions)
def suggestions(
    runner: Annotated[Any, Depends(automation)],
    cache: Annotated[AnswerCache, Depends(answers)],
    refresh: bool = False,
) -> Suggestions:
    """Up to twenty candidates and why the others were set aside, from the last discovery.

    Discovery reads the library and takes a while; the last list comes back at once and a fresh
    one is worked out behind it when it is a day old or `refresh` asks.
    """
    got = suggestions_answer(cache, runner, refresh=refresh)
    body = (
        Suggestions.model_validate(got.value)
        if got.value
        else Suggestions(candidates=[], skipped=[], error=None)
    )
    return body.model_copy(
        update={
            "computed_at": got.computed_at,
            "refreshing": got.refreshing,
            "error": got.error or body.error,
        }
    )


@router.post("/suggestions/run", response_model=AttemptView, status_code=202, responses={409: {}})
def run_suggestion(
    choice: RunSuggestion, runner: Annotated[Any, Depends(automation)]
) -> AttemptView | JSONResponse:
    """Start the candidate as `auto run` would: a lease, an attempt, the real CLI child."""
    try:
        started = runner.start_one(reason=SUGGESTION_REASON)
    except AutomationAlreadyRunningError:
        return JSONResponse({"detail": "Automation is already running."}, status_code=409)
    # WHY a thread: a generation runs for up to two hours; the page follows the attempt.
    threading.Thread(
        target=started.execute,
        kwargs={"candidate_key": choice.memory_key, "dry_run": choice.dry_run},
        daemon=True,
    ).start()
    return AttemptView(
        id=started.attempt.id, outcome="running", phase=None, reason=SUGGESTION_REASON, run_id=None
    )


@router.get("/automation/attempts/{attempt_id}", response_model=AttemptView)
def read_attempt(
    attempt_id: str, config: Annotated[Config, Depends(current_config)]
) -> AttemptView:
    """Where an automation attempt stands, and the run it opened, even a failed one."""
    attempt = AutomationStateStore(open_store(config)).get_attempt(attempt_id)
    if attempt is None:
        raise HTTPException(404, "No such attempt.")
    run_id = attempt.run_id
    if run_id is None:
        record = RunDatabase(open_store(config)).get_run_by_automation_attempt(attempt.id)
        run_id = record.run_id if record else None
    return AttemptView(
        id=attempt.id,
        outcome="dry_run" if attempt.outcome is AutoOutcome.DRY_RUN else attempt.outcome.value,
        phase=attempt.last_phase.label if attempt.last_phase else None,
        reason=attempt.error or attempt.reason,
        run_id=run_id,
    )
