"""Calendar-driven candidate detectors for smart automation.

Three detectors that propose memories based on calendar patterns:
monthly highlights, yearly reviews, and person spotlights.
"""

from __future__ import annotations

import calendar
from datetime import date

from immich_memories.automation.candidates import (
    CandidateCategory,
    MemoryCandidate,
    explain_empty,
    make_memory_key,
)
from immich_memories.automation.closeness import UNKNOWN_WEIGHT
from immich_memories.config_loader import Config
from immich_memories.i18n import get_ordinal
from immich_memories.memory_types.date_builders import build_birthday_windows
from immich_memories.timeperiod import DateRange, birthday_year, same_day_in_year


class MonthlyDetector:
    """Proposes a monthly highlight for the latest completed month only."""

    LOOKBACK_MONTHS = 1
    BASE_SCORE = 0.7

    def detect(
        self,
        assets_by_month: dict[str, int],
        people: list,
        generated_keys: set[str],
        config: Config,
        today: date,
        notes: list[str] | None = None,
    ) -> list[MemoryCandidate]:
        months = _last_n_completed_months(today, self.LOOKBACK_MONTHS)
        candidates = []

        for i, (year, month) in enumerate(months):
            key_str = f"{year}-{month:02d}"
            count = assets_by_month.get(key_str, 0)
            if count == 0:
                continue

            last_day = calendar.monthrange(year, month)[1]
            start = date(year, month, 1)
            end = date(year, month, last_day)
            mem_key = make_memory_key("monthly_highlights", start, end)

            if mem_key in generated_keys:
                continue

            # Most recent completed month gets full score, older ones decay
            recency = 1.0 - (i * 0.1)
            score = self.BASE_SCORE * max(recency, 0.3)

            reason = (
                f"{count} assets, most recent month"
                if i == 0
                else f"{count} assets, never generated"
            )

            candidates.append(
                MemoryCandidate(
                    memory_type="monthly_highlights",
                    category=CandidateCategory.MONTHLY_REVIEW,
                    date_range_start=start,
                    date_range_end=end,
                    person_names=[],
                    memory_key=mem_key,
                    score=round(score, 3),
                    reason=reason,
                    asset_count=count,
                )
            )

        reason = (
            "the last completed month has no pictures"
            if not any(assets_by_month.get(f"{year}-{month:02d}", 0) for year, month in months)
            else "the last completed month already has a film"
        )
        return explain_empty(candidates, notes, f"No month film: {reason}")


class YearlyDetector:
    """Proposes year-in-review memories for past years with content."""

    BASE_SCORE = 0.8
    # Wait until mid-January for late imports
    EARLIEST_DAY = 15

    def detect(
        self,
        assets_by_month: dict[str, int],
        people: list,
        generated_keys: set[str],
        config: Config,
        today: date,
        notes: list[str] | None = None,
    ) -> list[MemoryCandidate]:
        years_with_content = _years_from_assets(assets_by_month)
        candidates = []

        for year in sorted(years_with_content, reverse=True):
            # Only propose after Jan 15 of the following year
            cutoff = date(year + 1, 1, self.EARLIEST_DAY)
            if today < cutoff:
                continue

            start = date(year, 1, 1)
            end = date(year, 12, 31)
            mem_key = make_memory_key("year_in_review", start, end)

            if mem_key in generated_keys:
                continue

            total = sum(
                count
                for month_key, count in assets_by_month.items()
                if month_key.startswith(f"{year}-")
            )

            # More recent years score higher
            years_ago = today.year - year
            recency = 1.0 - (years_ago * 0.1)
            score = self.BASE_SCORE * max(recency, 0.3)

            candidates.append(
                MemoryCandidate(
                    memory_type="year_in_review",
                    category=CandidateCategory.YEAR_IN_REVIEW,
                    date_range_start=start,
                    date_range_end=end,
                    person_names=[],
                    memory_key=mem_key,
                    score=round(score, 3),
                    reason=f"{total} assets across the year, never generated",
                    asset_count=total,
                )
            )

        return explain_empty(
            candidates,
            notes,
            "No year film: no unfilmed year with pictures has reached January 15 of the following year",
        )


class PersonSpotlightDetector:
    """Proposes person spotlight memories for top people in the most recent full year."""

    BASE_SCORE = 0.6
    TOP_N = 5

    def detect(
        self,
        assets_by_month: dict[str, int],
        people: list,
        generated_keys: set[str],
        config: Config,
        today: date,
        person_asset_counts: dict[str, int] | None = None,
        upcoming_birthday_ids: set[str] | None = None,
        closeness: dict[str, float] | None = None,
        notes: list[str] | None = None,
    ) -> list[MemoryCandidate]:
        """``person_asset_counts`` counts each person's pictures in last year, not their lifetime.

        ``closeness`` weighs each person by how close the registry says they are (#2232).
        """
        if not people:
            return explain_empty(
                [],
                notes,
                "No person spotlight film: no named person with pictures in the previous year is eligible",
            )

        target_year = today.year - 1
        start = date(target_year, 1, 1)
        end = date(target_year, 12, 31)

        counts = person_asset_counts or {}
        skip_ids = upcoming_birthday_ids or set()

        # Filter to named people with thumbnails (proxy for "has content")
        # WHY: skip people with upcoming birthdays so BirthdayDetector fires instead
        visible = [p for p in people if p.name and p.thumbnail_path and p.id not in skip_ids]
        # WHY: counts are for the year the film reads; nobody with no picture in it can
        # make a film, however many they have across a lifetime (#2182)
        if person_asset_counts is not None:
            visible = [p for p in visible if counts.get(p.id, 0) > 0]
        if not visible:
            return explain_empty(
                [],
                notes,
                "No person spotlight film: no named person with pictures in the previous year is eligible",
            )

        # Sort by asset count if available, otherwise keep Immich default order
        if counts:
            visible.sort(key=lambda p: counts.get(p.id, 0), reverse=True)

        top = visible[: self.TOP_N]
        max_count = max((counts.get(p.id, 1) for p in top), default=1)

        candidates = []
        for rank, person in enumerate(top):
            name_lower = person.name.lower()
            mem_key = make_memory_key("person_spotlight", start, end, [name_lower])

            if mem_key in generated_keys:
                continue

            asset_count = counts.get(person.id, 0)
            appearance_ratio = (
                asset_count / max_count if max_count > 0 else (len(top) - rank) / len(top)
            )
            weight = (closeness or {}).get(person.id, UNKNOWN_WEIGHT)
            score = self.BASE_SCORE * max(0.2, appearance_ratio) * weight

            ordinal = get_ordinal(rank + 1)
            count_str = f", {asset_count} assets" if asset_count else ""
            reason = f"{ordinal} most featured person{count_str}"

            candidates.append(
                MemoryCandidate(
                    memory_type="person_spotlight",
                    category=CandidateCategory.PERSON_SPOTLIGHT,
                    date_range_start=start,
                    date_range_end=end,
                    person_names=[person.name],
                    memory_key=mem_key,
                    score=round(score, 3),
                    reason=reason,
                    asset_count=asset_count,
                )
            )

        return explain_empty(
            candidates,
            notes,
            "No person spotlight film: the eligible people already have films for the previous year",
        )


class OnThisDayDetector:
    """Proposes 'On This Day' memories for dates with rich content across years.

    Uses month-level data as a proxy — can only fire weekly (not daily) to avoid
    spamming since we can't distinguish good vs empty days within a month.
    Best paired with a once-per-week schedule.
    """

    BASE_SCORE = 0.35
    MIN_YEARS = 5

    def detect(
        self,
        assets_by_month: dict[str, int],
        people: list,
        generated_keys: set[str],
        config: Config,
        today: date,
        notes: list[str] | None = None,
    ) -> list[MemoryCandidate]:
        """Emit candidate if multiple prior years have content in today's month."""
        target_month_key = f"-{today.month:02d}"
        years_with_content = sorted(
            int(k.split("-")[0])
            for k in assets_by_month
            if k.endswith(target_month_key) and int(k.split("-")[0]) < today.year
        )

        if len(years_with_content) < self.MIN_YEARS:
            return explain_empty(
                [],
                notes,
                f"No on this day film: this month has pictures in {len(years_with_content)} prior years; it needs {self.MIN_YEARS}",
            )

        mem_key = make_memory_key(
            "on_this_day",
            date(today.year, today.month, today.day),
            date(today.year, today.month, today.day),
        )

        if mem_key in generated_keys:
            return explain_empty([], notes, "No on this day film: today's film already exists")

        n_years = len(years_with_content)
        year_span = f"{years_with_content[0]}-{years_with_content[-1]}"

        return [
            MemoryCandidate(
                memory_type="on_this_day",
                category=CandidateCategory.ON_THIS_DAY,
                date_range_start=date(today.year, today.month, today.day),
                date_range_end=date(today.year, today.month, today.day),
                person_names=[],
                memory_key=mem_key,
                score=round(self.BASE_SCORE * min(1.0, n_years / 10), 3),
                reason=f"Memories from this date across {n_years} years ({year_span})",
                asset_count=n_years,
                extra_params={"source_years": years_with_content},
            )
        ]


class BirthdayDetector:
    """Proposes person spotlight memories near a person's birthday."""

    BASE_SCORE = 0.75
    WINDOW_DAYS = 60
    # A film of someone seen on two outings is a slideshow of one afternoon (#2232).
    MIN_PICTURES = 50
    MIN_DAYS = 3
    # A birthday of the person seen least still gets half the score its closeness allows.
    MATERIAL_FLOOR = 0.5

    def detect(
        self,
        assets_by_month: dict[str, int],
        people: list,
        generated_keys: set[str],
        config: Config,
        today: date,
        person_asset_counts: dict[str, int] | None = None,
        closeness: dict[str, float] | None = None,
        busiest_count: int | None = None,
        distinct_days: dict[str, int] | None = None,
        notes: list[str] | None = None,
    ) -> list[MemoryCandidate]:
        """Emit candidates for people whose birthday was 2-60 days ago.

        ``person_asset_counts`` counts each person's pictures in the windows the birthday
        film reads (``birthday_film_windows``), not their lifetime. ``busiest_count`` is the
        most pictures any one person has, which the others are scaled against;
        ``distinct_days`` is how many days those pictures were taken on. A birthday that
        misses the minimum is left out and the reason is appended to ``notes``.
        """
        counts = person_asset_counts or {}
        busiest = max([busiest_count or 0, *counts.values()])
        candidates = []
        local_notes: list[str] = []

        for person in people:
            if not person.name or not person.birth_date:
                continue

            window = _completed_birthday_window(person.birth_date, today)
            if window is None:
                continue
            start, end, celebrated = window
            name_lower = person.name.lower()
            mem_key = make_memory_key("person_spotlight", start, end, [name_lower])

            if mem_key in generated_keys:
                continue

            asset_count = counts.get(person.id, 0)
            if person_asset_counts is not None and not self._enough_material(
                person, asset_count, (distinct_days or {}).get(person.id), local_notes
            ):
                continue

            candidates.append(
                self._candidate(
                    person,
                    (start, end),
                    mem_key,
                    asset_count,
                    celebrated.year - person.birth_date.year,
                    self._score(person.id, asset_count, busiest, closeness),
                )
            )

        if notes is not None:
            notes.extend(local_notes)
        if not local_notes:
            return explain_empty(
                candidates,
                notes,
                "No birthday film: no unfilmed birthday from 2 to 60 days ago has enough pictures",
            )
        return candidates

    def _enough_material(
        self, person, pictures: int, days: int | None, notes: list[str] | None
    ) -> bool:
        if pictures == 0:
            # Nothing in the film's windows: not worth a note, let alone a film.
            return False
        if pictures < self.MIN_PICTURES:
            shortfall = f"{pictures} pictures, it needs {self.MIN_PICTURES}"
        elif days is not None and days < self.MIN_DAYS:
            shortfall = f"{pictures} pictures over {days} days, it needs {self.MIN_DAYS} days"
        else:
            return True
        if notes is not None:
            notes.append(f"No birthday film for {person.name}: {shortfall}")
        return False

    def _candidate(
        self,
        person,
        window: tuple[date, date],
        mem_key: str,
        asset_count: int,
        age: int,
        score: float,
    ) -> MemoryCandidate:
        reason = (
            f"Birthday ({age} years old), {asset_count} assets"
            if asset_count
            else f"Birthday ({age} years old)"
        )
        return MemoryCandidate(
            memory_type="person_spotlight",
            category=CandidateCategory.BIRTHDAY,
            date_range_start=window[0],
            date_range_end=window[1],
            person_names=[person.name],
            memory_key=mem_key,
            score=round(score, 3),
            reason=reason,
            asset_count=asset_count,
            extra_params={"birthday": True, "birth_date": person.birth_date.isoformat()},
        )

    def _score(
        self, person_id: str, pictures: int, busiest: int, closeness: dict[str, float] | None
    ) -> float:
        weight = (closeness or {}).get(person_id, UNKNOWN_WEIGHT)
        if not busiest or not pictures:
            return self.BASE_SCORE * weight
        return self.BASE_SCORE * weight * max(self.MATERIAL_FLOOR, min(1.0, pictures / busiest))


def _completed_birthday_window(bday: date, today: date) -> tuple[date, date, date] | None:
    """The year a birthday film covers and the birthday that closed it, when one is due."""
    celebrated = _birthday_in_window(bday, today)
    if celebrated is None:
        return None
    span = birthday_year(bday, celebrated.year)
    return span.start.date(), span.end.date(), celebrated


def _birthday_in_window(bday: date, today: date) -> date | None:
    """The birthday just gone by, when it is old enough to have synced and recent enough to mark."""
    # WHY: 2-day minimum buffer after birthday to let photo sync happen
    most_recent_bday = same_day_in_year(bday, today.year)
    if most_recent_bday > today:
        most_recent_bday = same_day_in_year(bday, today.year - 1)
    days_since = (today - most_recent_bday).days
    if days_since < 2 or days_since > BirthdayDetector.WINDOW_DAYS:
        return None
    return most_recent_bday


def birthday_film_windows(bday: date, today: date) -> list[DateRange] | None:
    """What a birthday candidate's film reads, or None when no birthday is proposed today.

    The same windows ``generate --birthday`` fetches, so a count over them says whether
    that film will find anything.
    """
    most_recent_bday = _birthday_in_window(bday, today)
    if most_recent_bday is None:
        return None
    return build_birthday_windows(bday, most_recent_bday.year)


def _last_n_completed_months(today: date, n: int) -> list[tuple[int, int]]:
    """Return the last N completed (year, month) pairs before today's month."""
    result = []
    year, month = today.year, today.month
    for _ in range(n):
        # Step back one month
        month -= 1
        if month == 0:
            month = 12
            year -= 1
        result.append((year, month))
    return result


def _years_from_assets(assets_by_month: dict[str, int]) -> set[int]:
    """Extract unique years from YYYY-MM keyed asset counts."""
    years = set()
    for key in assets_by_month:
        try:
            years.add(int(key.split("-")[0]))
        except (ValueError, IndexError):
            continue
    return years
