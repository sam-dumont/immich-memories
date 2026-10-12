"""What a holiday film is made of: the holiday itself, each year, and its days around only when thin.

A holiday film reads a window of the holiday plus or minus two days in every year, because the
day itself is sometimes thin (a Christmas spent travelling, an Easter photographed the day
after). But the film is about the holiday: a busy weekend before it, or an outing the day
after, is not the holiday, and as the pool it took most of the film. So each year keeps the
pictures of the day itself, and the night that started on it; the rest of its window joins
only when the day holds fewer than `THIN_DAY` pictures. A year with nothing on the day did
not keep it, and adds nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
from typing import TypeVar

from immich_memories.timeperiod import DateRange

# A night that started on the holiday is still the holiday: the party ends after midnight.
SPILL_HOURS = 4
# Fewer pictures than this on the day itself, and the days around it fill in.
THIN_DAY = 5

_Item = TypeVar("_Item")


def holiday_day(window: DateRange) -> date:
    """The holiday a window is built around: its middle day (`build_holiday` centres it)."""
    return (window.start + (window.end - window.start) / 2).date()


def on_the_day(taken: datetime, day: date) -> bool:
    """Whether a picture taken at local time `taken` belongs to `day`, its night included."""
    return day in ((taken - timedelta(hours=SPILL_HOURS)).date(), taken.date())


def keep_the_day(
    groups: Sequence[Sequence[_Item]],
    windows: Sequence[DateRange],
    *,
    taken: Callable[[_Item], datetime],
) -> list[list[_Item]]:
    """Each of `groups` (the videos, the photos) narrowed to what a holiday film is made of.

    `windows` are the holiday's yearly windows; `taken` is an item's local capture time. The
    day's count is over every group together, so a day of three photos and three videos is
    not thin.
    """
    days = [(window, holiday_day(window)) for window in windows]

    def year_of(item: _Item) -> tuple[DateRange, date] | None:
        when = taken(item).replace(tzinfo=None)
        return next(
            (
                (window, day)
                for window, day in days
                if window.start.replace(tzinfo=None) <= when <= window.end.replace(tzinfo=None)
            ),
            None,
        )

    held: dict[date, int] = {}
    for group in groups:
        for item in group:
            found = year_of(item)
            if found is not None and on_the_day(taken(item), found[1]):
                held[found[1]] = held.get(found[1], 0) + 1

    def kept(item: _Item) -> bool:
        found = year_of(item)
        if found is None:
            return False
        day = found[1]
        count = held.get(day, 0)
        if count == 0:
            return False
        return count < THIN_DAY or on_the_day(taken(item), day)

    return [[item for item in group if kept(item)] for group in groups]
