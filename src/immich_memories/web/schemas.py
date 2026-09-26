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
