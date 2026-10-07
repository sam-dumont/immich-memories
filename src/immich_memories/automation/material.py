"""The picture counts the season, holiday and per-person detectors read from Immich.

Immich's timeline buckets stop at the month, so anything finer than a month is a read of
its own. Each read is scoped to a window a detector has already decided is due, so a
library with nothing due pays for none of them.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any

from immich_memories.timeperiod import DateRange

Window = tuple[date, date]


@dataclass(frozen=True)
class WindowFacts:
    """Pictures per whole-day window, as counted by the reads a detector asked for."""

    pictures: Mapping[Window, int] = field(default_factory=dict)
    # Pictures per day inside the window, for the detectors that need distinct days.
    days: Mapping[Window, Mapping[date, int]] = field(default_factory=dict)


def _range(window: Window) -> DateRange:
    first, last = window
    return DateRange(
        start=datetime.combine(first, time.min), end=datetime.combine(last, time(23, 59, 59))
    )


def pictures_in(clients: Iterable[Any], window: Window) -> int:
    """Everything the library holds taken inside the window, summed over the accounts."""
    span = _range(window)
    return sum(
        c.count_assets_with_people([], taken_after=span.start, taken_before=span.end)
        for c in clients
    )


def days_in(clients: Iterable[Any], window: Window) -> dict[date, int]:
    """Pictures per day inside the window, summed over the accounts."""
    span = _range(window)
    counted: Counter[date] = Counter()
    for client in clients:
        counted.update(_by_day(client.get_assets_for_date_range(span)))
    return dict(counted)


def person_days_in(clients: Iterable[tuple[Any, str]], window: Window) -> dict[date, int]:
    """Pictures of one person per day, over every (account client, local person id) they have."""
    span = _range(window)
    counted: Counter[date] = Counter()
    for client, person_id in clients:
        counted.update(_by_day(client.get_assets_for_person_and_date_range(person_id, span)))
    return dict(counted)


def _by_day(assets: Iterable[Any]) -> Counter[date]:
    # The wall-clock day the picture was taken, not the UTC one: a New Year's party is on
    # the night of the 31st wherever the phone was.
    return Counter((a.local_date_time or a.file_created_at).date() for a in assets)
