"""Backfill: the months of this year and last that never got a film (#2230)."""

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


class BackfillDetector:
    """Proposes months with no film, newest first, at a score only a quiet night reaches."""

    # Below a birthday (0.75), a trip and the regular monthly (0.7): backfill never wins a night
    # that has anything else to film.
    BASE_SCORE = 0.35
    MIN_PICTURES = 20

    def detect(
        self,
        assets_by_month: Mapping[str, int],
        generated_keys: Collection[str],
        today: date,
        proposed_keys: Collection[str] = (),
    ) -> Detection:
        """``proposed_keys`` are the other detectors' keys: a month they already offered is theirs."""
        latest = _previous_month(today.year, today.month)
        candidates = []
        for year in (today.year, today.year - 1):
            for month in range(12, 0, -1):
                if (year, month) >= (today.year, today.month) or (year, month) == latest:
                    continue
                count = assets_by_month.get(f"{year}-{month:02d}", 0)
                if count < self.MIN_PICTURES:
                    continue
                last_day = calendar.monthrange(year, month)[1]
                first, last = date(year, month, 1), date(year, month, last_day)
                key = make_manual_memory_key("monthly_highlights", first, last)
                if key in generated_keys or _taken(first, last, (*generated_keys, *proposed_keys)):
                    continue
                candidates.append(
                    MemoryCandidate(
                        memory_type="monthly_backfill",
                        category=CandidateCategory.BACKFILL,
                        date_range_start=first,
                        date_range_end=last,
                        person_names=[],
                        memory_key=key,
                        score=self.BASE_SCORE,
                        reason=f"{count} pictures in {first:%B %Y}, no film yet",
                        asset_count=count,
                    )
                )
        return Detection(candidates)


def _taken(first: date, last: date, keys: Collection[str]) -> bool:
    """The monthly and burst detectors write the same month with plain dates, in what they
    propose and in what an automatic run of theirs left behind."""
    return f"monthly_highlights:{first.isoformat()}:{last.isoformat()}:" in keys


def _previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)
