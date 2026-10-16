"""Time period utilities for flexible date range selection.

Supports:
- Full calendar years (Jan 1 - Dec 31)
- Birthday-based years (e.g., Feb 7, 2024 - Feb 7, 2025)
- Custom date ranges with start/end
- Period-based ranges (e.g., "6m" = 6 months from start)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import NamedTuple


class PeriodUnit(StrEnum):
    """Time period units."""

    DAYS = "d"
    WEEKS = "w"
    MONTHS = "m"
    YEARS = "y"


class DateRange(NamedTuple):
    """A date range with start and end dates."""

    start: datetime
    end: datetime

    @property
    def days(self) -> int:
        """Number of days in this range."""
        return (self.end.date() - self.start.date()).days + 1

    @property
    def description(self) -> str:
        """Human-readable description of the range."""
        if self.is_calendar_year:
            return f"Year {self.start.year}"

        start_str = self.start.strftime("%b %d, %Y")
        end_str = self.end.strftime("%b %d, %Y")
        return f"{start_str} - {end_str}"

    @property
    def is_calendar_year(self) -> bool:
        """Check if this is a full calendar year."""
        return (
            self.start.month == self.start.day == 1
            and self.end.month == 12
            and self.end.day == 31
            and self.start.year == self.end.year
        )

    def contains(self, dt: datetime | date) -> bool:
        """Whether a moment falls in the range, the whole of its last second included.

        A naive bound is a calendar time, read on the moment's own clock: given a picture's
        ``local_taken_at``, 20:30 on 31 December eight hours behind UTC is in that year, though it
        is 1 January in UTC (#2355). An aware bound is an instant. A date is its midnight.
        An end of 23:59:59 holds 23:59:59.5: the bound is the next second, exclusive.
        """
        if isinstance(dt, date) and not isinstance(dt, datetime):
            dt = datetime.combine(dt, time.min)
        return within(dt, self.start, self.end)


def within(moment: datetime, start: datetime | None, end: datetime | None) -> bool:
    """Whether `moment` falls between two bounds, either of which may be open.

    The bounds follow `DateRange.contains`: naive ones are read on the moment's own clock,
    aware ones are instants, and the end holds the whole of its last second.
    """
    if start is not None and _on_clock_of(start, moment) < _on_clock_of(start, start):
        return False
    if end is None:
        return True
    after = end.replace(microsecond=0) + timedelta(seconds=1)
    return _on_clock_of(end, moment) < _on_clock_of(end, after)


def _on_clock_of(bound: datetime, moment: datetime) -> datetime:
    """`moment` in the terms `bound` is written in: wall-clock digits, or a UTC instant.

    Aware values go through UTC because Python compares two datetimes sharing a zone by
    their digits, which reads the repeated autumn hour as one hour.
    """
    if bound.tzinfo is None:
        return moment.replace(tzinfo=None)
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


@dataclass
class Period:
    """A time period with a value and unit."""

    value: int
    unit: PeriodUnit

    @classmethod
    def parse(cls, period_str: str) -> Period:
        """Parse a period string like '6m', '1y', '2w', '30d'.

        Args:
            period_str: Period string (e.g., "6m", "1y", "2w", "30d")

        Returns:
            Period object

        Raises:
            ValueError: If period string is invalid
        """
        period_str = period_str.strip().lower()
        match = re.match(r"^(\d+)\s*([dwmy])$", period_str)

        if not match:
            raise ValueError(
                f"Invalid period format: '{period_str}'. "
                "Expected format: number + unit (d/w/m/y). "
                "Examples: '6m', '1y', '2w', '30d'"
            )

        value = int(match.group(1))
        unit_char = match.group(2)

        unit_map = {
            "d": PeriodUnit.DAYS,
            "w": PeriodUnit.WEEKS,
            "m": PeriodUnit.MONTHS,
            "y": PeriodUnit.YEARS,
        }

        return cls(value=value, unit=unit_map[unit_char])

    def add_to_date(self, start: date | datetime) -> datetime:
        """Add this period to a start date.

        Args:
            start: Starting date/datetime

        Returns:
            End datetime after adding the period
        """
        if isinstance(start, date) and not isinstance(start, datetime):
            start = datetime.combine(start, datetime.min.time())

        if self.unit == PeriodUnit.DAYS:
            return start + timedelta(days=self.value)

        if self.unit == PeriodUnit.WEEKS:
            return start + timedelta(weeks=self.value)

        if self.unit == PeriodUnit.MONTHS:
            # Add months while handling edge cases
            year = start.year + (start.month + self.value - 1) // 12
            month = (start.month + self.value - 1) % 12 + 1

            # Handle day overflow (e.g., Jan 31 + 1 month)
            import calendar

            max_day = calendar.monthrange(year, month)[1]
            day = min(start.day, max_day)

            return start.replace(year=year, month=month, day=day)

        if self.unit == PeriodUnit.YEARS:
            try:
                return start.replace(year=start.year + self.value)
            except ValueError:
                # Handle Feb 29 on non-leap year
                return start.replace(year=start.year + self.value, month=2, day=28)

        raise ValueError(f"Unknown period unit: {self.unit}")

    def __str__(self) -> str:
        """Return period as string (e.g., '6m')."""
        return f"{self.value}{self.unit.value}"


def calendar_year(year: int) -> DateRange:
    """Get date range for a full calendar year.

    Args:
        year: The calendar year (e.g., 2024)

    Returns:
        DateRange from Jan 1 to Dec 31 of that year
    """
    return DateRange(
        start=datetime(year, 1, 1, 0, 0, 0),
        end=datetime(year, 12, 31, 23, 59, 59),
    )


def same_day_in_year(day: date, year: int) -> date:
    """The day an annual date falls on in a given year.

    29 February lands on the 28th in a year that has no 29th, which is the
    reading a birthday takes everywhere else in the world.
    """
    try:
        return date(year, day.month, day.day)
    except ValueError:
        return date(year, 2, 28)


def birthday_year(
    birthday: date | datetime,
    year: int | None = None,
) -> DateRange:
    """A yearly review of a person's life, from one birthday through the next.

    ``year`` names the birthday being celebrated, not a calendar year to run
    forward from: the window starts on the previous birthday and ends on this
    one, both days included. A birthday film is a yearly review starting from
    the birthdate (owner ruling), so last year's party opens it and this
    year's closes it.

    Example:
        birthday_year(date(1990, 2, 7), 2026)
        -> Feb 7, 2025 to Feb 7, 2026
    """
    if year is None:
        year = datetime.now().year

    celebrated = same_day_in_year(birthday, year)
    previous = same_day_in_year(birthday, year - 1)

    start = datetime.combine(previous, time.min)
    end = datetime.combine(celebrated, time(23, 59, 59))
    return DateRange(start=start, end=end)


def from_period(
    start: date | datetime,
    period: str | Period,
) -> DateRange:
    """Create date range from start date and period.

    Args:
        start: Starting date/datetime
        period: Period string (e.g., "6m") or Period object

    Returns:
        DateRange from start to start + period - 1 day

    Example:
        from_period(date(2024, 1, 1), "6m")
        -> Jan 1, 2024 to Jun 30, 2024
    """
    if isinstance(start, date) and not isinstance(start, datetime):
        start = datetime.combine(start, datetime.min.time())

    if isinstance(period, str):
        period = Period.parse(period)

    # End is period from start, minus 1 day, at end of day
    end = (period.add_to_date(start) - timedelta(days=1)).replace(hour=23, minute=59, second=59)

    return DateRange(
        start=start,
        end=end,
    )


def custom_range(
    start: date | datetime,
    end: date | datetime,
) -> DateRange:
    """Create custom date range.

    Args:
        start: Start date/datetime
        end: End date/datetime

    Returns:
        DateRange with proper time bounds

    Raises:
        ValueError: If end is before start
    """
    if isinstance(start, date) and not isinstance(start, datetime):
        start = datetime.combine(start, datetime.min.time())

    if isinstance(end, date) and not isinstance(end, datetime):
        end = datetime.combine(end, datetime.max.time().replace(microsecond=0))
    else:
        # Ensure end is at end of day
        end = end.replace(hour=23, minute=59, second=59)

    if end < start:
        raise ValueError(f"End date ({end.date()}) cannot be before start date ({start.date()})")

    return DateRange(start=start, end=end)


def parse_date(date_str: str) -> date:
    """Parse an RFC 3339 full date: YYYY-MM-DD, and nothing else.

    07/02 meant July to one flag and February to another until the dialects
    were removed (#748). A rejected date names the format; a guessed one
    silently builds the wrong memory.
    """
    date_str = date_str.strip()
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(
            f"Cannot parse date: '{date_str}'. Dates are RFC 3339: YYYY-MM-DD "
            f"(for example 2024-02-07)."
        ) from None
