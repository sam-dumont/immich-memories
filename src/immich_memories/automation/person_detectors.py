"""A monthly film for each person close to the owner (#2231)."""

from __future__ import annotations

import calendar
from collections.abc import Collection, Mapping
from datetime import date

from immich_memories.automation.candidates import (
    CandidateCategory,
    Detection,
    MemoryCandidate,
    make_manual_memory_key,
)


class PersonMonthlyDetector:
    """Proposes a person's last completed month, and the two before it as backfill."""

    BASE_SCORE = 0.6
    BACKFILL_SCORE = 0.35
    MIN_PICTURES = 15
    MIN_DAYS = 4
    LOOKBACK_MONTHS = 3

    def detect(
        self,
        people: list,
        close_ids: Collection[str],
        person_days: Mapping[str, Mapping[date, int]],
        generated_keys: Collection[str],
        today: date,
    ) -> Detection:
        """``person_days`` holds each close person's pictures per day over the lookback."""
        candidates: list[MemoryCandidate] = []
        thin: list[str] = []
        for person in people:
            if person.id not in close_ids or not person.name:
                continue
            counted = person_days.get(person.id, {})
            year, month = today.year, today.month
            for back in range(self.LOOKBACK_MONTHS):
                year, month = _previous_month(year, month)
                found, short = self._month(person, counted, year, month, back, generated_keys)
                if found:
                    candidates.append(found)
                elif short and back == 0:
                    thin.append(person.name)
        notes = self._note(thin, today)
        if not candidates and not notes:
            reason = (
                "no named people are marked close in the people registry"
                if not any(p.id in close_ids and p.name for p in people)
                else f"no unfilmed month in the last three has {self.MIN_PICTURES} pictures over {self.MIN_DAYS} days"
            )
            notes = (f"No person month film: {reason}",)
        return Detection(candidates, notes)

    def _note(self, thin: list[str], today: date) -> tuple[str, ...]:
        if not thin:
            return ()
        who = ", ".join(thin) if len(thin) <= 3 else f"{len(thin)} close people"
        last = _previous_month(today.year, today.month)
        return (
            f"No {calendar.month_name[last[1]]} film for {who}: under {self.MIN_PICTURES} "
            f"pictures over {self.MIN_DAYS} days",
        )

    def _month(
        self,
        person,
        counted: Mapping[date, int],
        year: int,
        month: int,
        back: int,
        generated_keys: Collection[str],
    ) -> tuple[MemoryCandidate | None, bool]:
        first = date(year, month, 1)
        last = date(year, month, calendar.monthrange(year, month)[1])
        key = make_manual_memory_key("monthly_highlights", first, last, [person.name])
        if key in generated_keys:
            return None, False
        days = {d: n for d, n in counted.items() if first <= d <= last}
        pictures = sum(days.values())
        if pictures < self.MIN_PICTURES or len(days) < self.MIN_DAYS:
            return None, True
        return (
            MemoryCandidate(
                memory_type="person_monthly",
                category=CandidateCategory.PERSON_MONTHLY,
                date_range_start=first,
                date_range_end=last,
                person_names=[person.name],
                memory_key=key,
                score=self.BASE_SCORE if back == 0 else self.BACKFILL_SCORE,
                reason=f"{person.name} in {first:%B %Y}, {pictures} pictures over {len(days)} days",
                asset_count=pictures,
            ),
            False,
        )


def _previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)
