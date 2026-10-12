"""Season and holiday candidates: the films the calendar owes a library (#2227, #2228)."""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median

from immich_memories.automation.candidates import (
    CandidateCategory,
    Detection,
    MemoryCandidate,
    make_manual_memory_key,
)
from immich_memories.automation.material import Window
from immich_memories.memory_types.date_builders import (
    HOLIDAY_REACH_YEARS,
    build_season,
    holiday_name,
    holidays_of,
    resolve_holiday,
)
from immich_memories.timeperiod import same_day_in_year

# A film about a stretch of time waits for the pictures to sync, and stops being news.
_WAIT_DAYS = 3


@dataclass(frozen=True)
class SeasonDue:
    """The season that just ended and has no film yet."""

    season: str
    hemisphere: str
    start: date
    end: date

    @property
    def window(self) -> Window:
        return (self.start, self.end)


class SeasonDetector:
    """Proposes the season that just ended, once per season-year."""

    BASE_SCORE = 0.6
    LAST_DAYS = 30
    MIN_PICTURES = 40
    MIN_DAYS = 6

    def due(
        self, today: date, hemisphere: str | None, generated_keys: Collection[str]
    ) -> SeasonDue | None:
        """The season whose window is open today, unless a film of it exists."""
        if hemisphere is None:
            return None
        # Winter starts in December, so the one that ended this February began last year.
        for year in (today.year - 1, today.year):
            for name in ("spring", "summer", "fall", "winter"):
                span = build_season(name, year, hemisphere)
                start, end = span.start.date(), span.end.date()
                if not _WAIT_DAYS <= (today - end).days <= self.LAST_DAYS:
                    continue
                if make_manual_memory_key("season", start, end) in generated_keys:
                    return None
                return SeasonDue(name, hemisphere, start, end)
        return None

    def detect(
        self,
        today: date,
        hemisphere: str | None,
        generated_keys: Collection[str],
        days: Mapping[Window, Mapping[date, int]],
    ) -> Detection:
        """``days`` holds the pictures per day of the window `due` named."""
        if hemisphere is None:
            return Detection(
                notes=(
                    "No season film: the home base is not set (trips.homebase_latitude and "
                    "trips.homebase_longitude), so the hemisphere is unknown",
                )
            )
        due = self.due(today, hemisphere, generated_keys)
        if due is None:
            reason = (
                "the season already has a film"
                if self.due(today, hemisphere, ()) is not None
                else "no season ended between 3 and 30 days ago"
            )
            return Detection(notes=(f"No season film: {reason}",))
        counted = days.get(due.window, {})
        pictures, distinct = sum(counted.values()), len(counted)
        if pictures < self.MIN_PICTURES or distinct < self.MIN_DAYS:
            return Detection(
                notes=(
                    f"No {due.season} film: {pictures} pictures over {distinct} days, "
                    f"it needs {self.MIN_PICTURES} pictures over {self.MIN_DAYS} days",
                )
            )
        return Detection(
            [
                MemoryCandidate(
                    memory_type="season",
                    category=CandidateCategory.SEASON,
                    date_range_start=due.start,
                    date_range_end=due.end,
                    person_names=[],
                    memory_key=make_manual_memory_key("season", due.start, due.end),
                    score=self.BASE_SCORE,
                    reason=f"{due.season.capitalize()} just ended, {pictures} pictures over {distinct} days",
                    asset_count=pictures,
                    extra_params={"season": due.season, "hemisphere": due.hemisphere},
                )
            ]
        )


@dataclass(frozen=True)
class HolidayDue:
    """One occurrence of a holiday, with the holiday's day in every year its film would read."""

    argument: str
    name: str
    year: int
    # The holiday in each year, most recent first: this year's occurrence, then every
    # earlier one back to `HOLIDAY_REACH_YEARS`, as `generate --holiday` reads them.
    days: tuple[date, ...]
    window_days: int = 2

    def window_of(self, day: date) -> Window:
        span = timedelta(days=self.window_days)
        return (day - span, day + span)

    @property
    def windows(self) -> tuple[Window, ...]:
        return tuple(self.window_of(day) for day in self.days)

    @property
    def start(self) -> date:
        return self.windows[-1][0]

    @property
    def end(self) -> date:
        return self.windows[0][1]


# The holidays a household is taken to keep before it says anything: the ones nearly every
# library photographs. The home country's calendar and `extra_holidays` come on top. Being on
# a list never makes a film on its own: the pictures must show the day was kept.
CELEBRATED_HOLIDAYS = ("christmas", "new_year", "easter")


def marked_year(day: date, counted: Mapping[date, int], window_days: int = 2) -> bool:
    """Whether one year's pictures show the holiday was kept: the day stands out.

    The day needs `HolidayDetector.MIN_DAY_PICTURES` pictures, and at least
    `HolidayDetector.STANDS_OUT` times the median of the days around it (two either side).
    The median, not the mean: one busy neighbour (an outing the day before) must not hide a
    day that stands out against the rest of its week.
    """
    on_the_day = counted.get(day, 0)
    if on_the_day < HolidayDetector.MIN_DAY_PICTURES:
        return False
    around = [
        counted.get(day + timedelta(days=offset), 0)
        for offset in range(-window_days, window_days + 1)
        if offset
    ]
    return on_the_day >= HolidayDetector.STANDS_OUT * median(around)


class HolidayDetector:
    """Proposes a holiday the household keeps, across every year the library holds.

    A holiday qualifies when the pictures show it was kept: in at least `MIN_MARKED_YEARS`
    years the day itself holds `MIN_DAY_PICTURES` pictures and `STANDS_OUT` times the median
    of the four days around it. The date alone never qualifies.
    """

    BASE_SCORE = 0.6
    REACH_YEARS = HOLIDAY_REACH_YEARS
    WINDOW_DAYS = 2
    MIN_DAY_PICTURES = 10
    STANDS_OUT = 2
    MIN_MARKED_YEARS = 3
    _WAIT_DAYS = _WAIT_DAYS
    _LAST_DAYS = 365

    def due(
        self,
        today: date,
        country: str | None,
        extra_holidays: Collection[str],
        generated_keys: Collection[str],
    ) -> list[HolidayDue]:
        """Every holiday of the last year whose film is open and not yet made."""
        due: list[HolidayDue] = []
        filmed = _filmed_holiday_ends(generated_keys)
        for centre, argument, name in _occurrences(today, country, extra_holidays):
            try:
                days = self._days(argument, centre.year, country)
            except ValueError:
                # `generate --holiday` would refuse this one too: some year it is not kept.
                continue
            if days[0] != centre:
                # The name does not resolve back to this day (two holidays on one date).
                continue
            found = HolidayDue(argument, name, centre.year, days, self.WINDOW_DAYS)
            # Once per holiday-year, however many years the film was made over: a film made
            # by hand with --years-back, or before every year was read, still counts.
            if found.end not in filmed:
                due.append(found)
        return due

    def _days(self, argument: str, year: int, country: str | None) -> tuple[date, ...]:
        return tuple(
            resolve_holiday(argument, year - back, country=country or "US")
            for back in range(self.REACH_YEARS)
        )

    def detect(
        self,
        today: date,
        country: str | None,
        extra_holidays: Collection[str],
        generated_keys: Collection[str],
        days: Mapping[Window, Mapping[date, int]],
    ) -> Detection:
        """``days`` holds the pictures per day of every window `due` names that was read."""
        candidates = []
        due_holidays = self.due(today, country, extra_holidays, generated_keys)
        for due in due_holidays:
            counted = [(day, days.get(due.window_of(day), {})) for day in due.days]
            marked = sorted(day.year for day, per_day in counted if marked_year(day, per_day))
            if len(marked) < self.MIN_MARKED_YEARS:
                continue
            on_the_day = sum(per_day.get(day, 0) for day, per_day in counted)
            years = sum(1 for day, per_day in counted if per_day.get(day, 0) > 0)
            score = self.BASE_SCORE * (0.5 + 0.5 * min(len(marked), 5) / 5)
            candidates.append(
                MemoryCandidate(
                    memory_type="holiday",
                    category=CandidateCategory.HOLIDAY,
                    date_range_start=due.start,
                    date_range_end=due.end,
                    person_names=[],
                    memory_key=make_manual_memory_key("holiday", due.start, due.end),
                    score=round(score, 3),
                    reason=(
                        f"{due.name}: the day stands out in {len(marked)} years "
                        f"({_years_text(marked)}), {on_the_day} pictures on it across {years} years"
                    ),
                    asset_count=on_the_day,
                    extra_params={
                        "holiday": due.argument,
                        "year": due.year,
                        "years_with_material": years,
                        "marked_years": marked,
                    },
                )
            )
        if candidates:
            return Detection(candidates)
        reason = (
            "no unfilmed holiday is due"
            if not due_holidays
            else (
                f"no unfilmed holiday stands out in {self.MIN_MARKED_YEARS} years: the day "
                f"needs {self.MIN_DAY_PICTURES} pictures and {self.STANDS_OUT} times the days "
                "around it"
            )
        )
        return Detection(notes=(f"No holiday film: {reason}",))


def _years_text(years: list[int]) -> str:
    return ", ".join(str(year) for year in years)


_HOLIDAY_KEY = re.compile(
    r"^holiday:\d{4}-\d{2}-\d{2}(?:T00:00:00)?:(\d{4}-\d{2}-\d{2})(?:T23:59:59)?:"
)


def _filmed_holiday_ends(generated_keys: Collection[str]) -> set[date]:
    """The last day of every holiday film made: the occurrence it was about."""
    ends = set()
    for key in generated_keys:
        if (found := _HOLIDAY_KEY.match(key)) is not None:
            ends.add(date.fromisoformat(found[1]))
    return ends


def _occurrences(
    today: date, country: str | None, extra_holidays: Collection[str]
) -> list[tuple[date, str, str]]:
    """(day, the argument `generate --holiday` takes, the name) for each holiday in the last year."""
    found: dict[date, tuple[str, str]] = {}
    for year in (today.year - 1, today.year):
        for key in CELEBRATED_HOLIDAYS:
            found[resolve_holiday(key, year, country=country or "US")] = (key, holiday_name(key))
        if country:
            for day, name in holidays_of(year, country).items():
                found.setdefault(day, (name, name))
        for entry in extra_holidays:
            month_day, _, name = entry.partition(":")
            # 29 February falls on the 28th in a year without one, as `generate --holiday` reads it.
            day = same_day_in_year(date(2000, int(month_day[:2]), int(month_day[3:5])), year)
            found[day] = (month_day.strip(), name.strip() or month_day.strip())
    return sorted(
        (day, arg, name)
        for day, (arg, name) in found.items()
        if HolidayDetector._WAIT_DAYS <= (today - day).days <= HolidayDetector._LAST_DAYS
    )
