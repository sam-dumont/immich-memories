"""Stage-1 gather facts for the person annotation layer, from metadata alone.

The doctrine (docs/implementation-plans/2026-08-31-person-annotation-layer.md):
shares over the library's own photographed time, never raw counts. The people graph
reads that time in months, the grain Immich's timeline answers in.
"""

from __future__ import annotations

from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Era:
    """A declared span over which presence and absence are read together."""

    name: str
    start: date | None = None
    end: date | None = None

    def contains(self, day: date) -> bool:
        if self.start is not None and day < self.start:
            return False
        return not (self.end is not None and day > self.end)


# The one era every library shares, bounds from the spec. Pre-smartphone and
# parenthood spans are library-specific and arrive owner-declared or detected.
# How to read it: gaps are circumstance, never distance; the 2021 rebound
# inflates reunions.
COVID_ERA = Era(
    "covid",
    start=date(2020, 3, 1),
    end=date(2022, 6, 30),
)


def era_day_share(
    person_days: set[date], library_days: AbstractSet[date], era: Era
) -> float | None:
    """The share of the era's photographed library days that include the person.

    None when the library photographed nothing in the era — a share over zero
    days is not a small share, it is no evidence at all.
    """
    era_library_days = {day for day in library_days if era.contains(day)}
    if not era_library_days:
        return None
    return len(person_days & era_library_days) / len(era_library_days)


def era_day_shares(
    person_days: set[date],
    library_days: AbstractSet[date],
    *,
    eras: tuple[Era, ...] = (COVID_ERA,),
) -> tuple[tuple[str, float], ...]:
    """One (era name, share) row per era the library actually photographed."""
    rows = []
    for era in eras:
        share = era_day_share(person_days, library_days, era)
        if share is not None:
            rows.append((era.name, share))
    return tuple(rows)
