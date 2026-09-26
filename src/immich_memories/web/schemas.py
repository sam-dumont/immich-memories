"""The /api/v1 contract. The TypeScript client is generated from these models."""

from __future__ import annotations

from datetime import UTC, date, datetime

from pydantic import BaseModel, field_serializer


class RunSummary(BaseModel):
    run_id: str
    status: str
    source: str
    created_at: datetime
    memory_type: str | None
    date_range_start: date | None
    date_range_end: date | None
    preview_asset_ids: list[str]

    @field_serializer("created_at")
    def _rfc3339(self, value: datetime) -> str:
        # Runs record UTC today; an older row without a zone was `datetime.now()`, server-local
        # time, which is how astimezone() reads a naive value.
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class RunPage(BaseModel):
    runs: list[RunSummary]
    next_offset: int | None


class SelectionPath(BaseModel):
    """What the rules decided about a picture, in the words `runs why` prints."""

    facts: str
    passed: list[str]
    left_out_at: str | None
    left_out_because: str | None
    kept_at: str | None


class ModelDecision(BaseModel):
    """What the model polish recorded about a shot; absent when no model read the cut."""

    model_reason: str
    kept_reason: str
    proposed_asset_id: str
    offered_count: int
    replacement_outcome: str
    replaced_asset_id: str
    seat: str


class CutShot(BaseModel):
    asset_id: str
    position: int
    start: float
    seconds: float
    taken: str
    day: str
    new_day: bool
    chapter: str
    story_key: str
    story_title: str
    moment: str
    reason: str
    motion: bool
    source_interval: tuple[float, float] | None
    selection: SelectionPath | None
    model: ModelDecision | None


class Cut(BaseModel):
    run_id: str
    thesis: str
    content_seconds: float
    film_seconds: float | None
    model_polish: bool
    shots: list[CutShot]


class PhaseTiming(BaseModel):
    name: str
    seconds: float
    errors: list[str]


class RunDetail(RunSummary):
    completed_at: datetime | None
    output_path: str | None
    delivery_status: str
    warnings: list[str]
    phases: list[PhaseTiming]
    clips_selected: int
    has_cut: bool
    child_output: bool
