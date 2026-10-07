"""Memory candidate detection — data models and dedup key generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import StrEnum
from typing import Any

from immich_memories.api.person_expression import PersonExpression


class CandidateCategory(StrEnum):
    """The detector identity of a proposed memory."""

    MONTHLY_REVIEW = "monthly_review"
    ACTIVITY_BURST = "activity_burst"
    YEAR_IN_REVIEW = "year_in_review"
    PERSON_SPOTLIGHT = "person_spotlight"
    BIRTHDAY = "birthday"
    MULTI_PERSON = "multi_person"
    ON_THIS_DAY = "on_this_day"
    TRIP = "trip"
    # Named for the family rather than for the catalogue: what makes this kind
    # of proposal different is that the library volunteered it, not that it is
    # a day. A recurring subject aggregated out of the analysis corpus is the
    # same thing at another granularity and reads as this member's sibling.
    EMERGENT_DAY = "emergent_day"
    # One category per detector that has a cap and a cooldown of its own. Backfill and the
    # per-person months render as monthly_highlights, but filed under the monthly's category
    # they would share its cap of three and the "one monthly per calendar month" rule.
    SEASON = "season"
    HOLIDAY = "holiday"
    ALBUM = "album"
    BACKFILL = "backfill"
    PERSON_MONTHLY = "person_monthly"


@dataclass
class MemoryCandidate:
    """A proposed memory that could be generated next."""

    memory_type: str
    category: CandidateCategory
    date_range_start: date
    date_range_end: date
    person_names: list[str]
    memory_key: str
    score: float
    reason: str
    asset_count: int
    extra_params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Bind grouped scope before discovery dedup, backoff or launch reads the key."""
        record = self.extra_params.get("person_expression")
        if record is None:
            return
        expression = (
            record if isinstance(record, PersonExpression) else PersonExpression.from_dict(record)
        )
        if self.person_names and set(self.person_names) != set(expression.leaf_values):
            raise ValueError("candidate names and grouped people condition disagree")
        self.person_names = list(expression.leaf_values)
        self.extra_params = self.extra_params | {"person_expression": expression.to_dict()}
        self.memory_key = bind_people_expression_key(self.memory_key, expression)


def make_memory_key(
    memory_type: str,
    date_range_start: date,
    date_range_end: date,
    person_names: list[str] | None = None,
    discriminator: str | None = None,
    person_expression: PersonExpression | None = None,
) -> str:
    """Build a deterministic dedup fingerprint for a memory.

    Format: {type}:{start}:{end}:{sorted,lowered,persons}[:{discriminator}]
    Same inputs always produce the same key, regardless of person order or case.

    The discriminator is for a memory that is allowed to come back: the same
    day proposed on its tenth anniversary and again on its fifteenth is two
    memories, and without it the second could never fire. Keys already written
    carry no discriminator and no trailing colon, so every one of them still
    matches the run that wrote it.
    """
    persons = ",".join(sorted(n.lower() for n in (person_names or [])))
    suffix = f":{discriminator}" if discriminator else ""
    key = (
        f"{memory_type}:{date_range_start.isoformat()}:"
        f"{date_range_end.isoformat()}:{persons}{suffix}"
    )
    return bind_people_expression_key(key, person_expression)


def make_manual_memory_key(
    memory_type: str,
    first_day: date,
    last_day: date,
    person_names: list[str] | None = None,
    discriminator: str | None = None,
) -> str:
    """The key a hand-made `generate` run records for a whole-day window.

    A manual run keeps the window as datetimes (midnight to 23:59:59), so its key reads
    `...:2025-06-01T00:00:00:2025-06-30T23:59:59:`. A detector that builds its key this way
    sees a film made by hand as already made.
    """
    return make_memory_key(
        memory_type,
        datetime.combine(first_day, time.min),
        datetime.combine(last_day, time(23, 59, 59)),
        person_names,
        discriminator,
    )


@dataclass(frozen=True)
class Detection:
    """What a detector proposed, and why it proposed nothing where it could have."""

    candidates: list[MemoryCandidate] = field(default_factory=list)
    notes: tuple[str, ...] = ()


def bind_people_expression_key(key: str, expression: PersonExpression | None) -> str:
    """The same people under different conditions are different requested memories."""
    if expression is None:
        return key
    import hashlib
    import json

    serialized = json.dumps(expression.to_dict(), sort_keys=True, separators=(",", ":"))
    suffix = ":people-" + hashlib.sha256(serialized.encode()).hexdigest()[:16]
    return key if key.endswith(suffix) else key + suffix
