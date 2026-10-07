"""Season and holiday candidates: the films the calendar owes a library (#2227, #2228)."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date, timedelta

from immich_memories.automation.candidates import (
    CandidateCategory,
    Detection,
    MemoryCandidate,
    make_manual_memory_key,
)
from immich_memories.automation.material import Window
from immich_memories.memory_types.date_builders import build_season, holidays_of, resolve_holiday

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
            return Detection()
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
    """One occurrence of a holiday, with the five yearly windows its film would read."""

    argument: str
    name: str
    year: int
    windows: tuple[Window, ...]

    @property
    def start(self) -> date:
        return self.windows[-1][0]

    @property
    def end(self) -> date:
        return self.windows[0][1]


class HolidayDetector:
    """Proposes a holiday film across the years that have pictures around it."""

    BASE_SCORE = 0.6
    YEARS_BACK = 5
    WINDOW_DAYS = 2
    MIN_YEARS = 2
    MIN_PICTURES = 20
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
        for centre, argument, name in _occurrences(today, country, extra_holidays):
            try:
                windows = self._windows(argument, centre.year, country)
            except ValueError:
                # `generate --holiday` would refuse this one too: some year it is not kept.
                continue
            if windows[0][0] + timedelta(days=self.WINDOW_DAYS) != centre:
                # The name does not resolve back to this day (two holidays on one date).
                continue
            found = HolidayDue(argument, name, centre.year, windows)
            key = make_manual_memory_key("holiday", found.start, found.end)
            if key not in generated_keys:
                due.append(found)
        return due

    def _windows(self, argument: str, year: int, country: str | None) -> tuple[Window, ...]:
        windows = []
        for back in range(self.YEARS_BACK):
            centre = resolve_holiday(argument, year - back, country=country or "US")
            span = timedelta(days=self.WINDOW_DAYS)
            windows.append((centre - span, centre + span))
        return tuple(windows)

    def detect(
        self,
        today: date,
        country: str | None,
        extra_holidays: Collection[str],
        generated_keys: Collection[str],
        pictures: Mapping[Window, int],
    ) -> Detection:
        """``pictures`` holds the count for every window `due` names."""
        candidates = []
        for due in self.due(today, country, extra_holidays, generated_keys):
            counts = [pictures.get(window, 0) for window in due.windows]
            total, years = sum(counts), sum(1 for n in counts if n > 0)
            if years < self.MIN_YEARS or total < self.MIN_PICTURES:
                continue
            score = self.BASE_SCORE * (0.5 + 0.5 * min(years, self.YEARS_BACK) / self.YEARS_BACK)
            candidates.append(
                MemoryCandidate(
                    memory_type="holiday",
                    category=CandidateCategory.HOLIDAY,
                    date_range_start=due.start,
                    date_range_end=due.end,
                    person_names=[],
                    memory_key=make_manual_memory_key("holiday", due.start, due.end),
                    score=round(score, 3),
                    reason=f"{due.name}: {total} pictures across {years} years",
                    asset_count=total,
                    extra_params={
                        "holiday": due.argument,
                        "year": due.year,
                        "years_with_material": years,
                    },
                )
            )
        return Detection(candidates)


def _occurrences(
    today: date, country: str | None, extra_holidays: Collection[str]
) -> list[tuple[date, str, str]]:
    """(day, the argument `generate --holiday` takes, the name) for each holiday in the last year."""
    found: dict[date, tuple[str, str]] = {}
    for year in (today.year - 1, today.year):
        if country:
            for day, name in holidays_of(year, country).items():
                found.setdefault(day, (name, name))
        for entry in extra_holidays:
            month_day, _, name = entry.partition(":")
            day = date(year, int(month_day[:2]), int(month_day[3:5]))
            found[day] = (month_day.strip(), name.strip() or month_day.strip())
    return sorted(
        (day, arg, name)
        for day, (arg, name) in found.items()
        if HolidayDetector._WAIT_DAYS <= (today - day).days <= HolidayDetector._LAST_DAYS
    )
