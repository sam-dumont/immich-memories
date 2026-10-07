"""Backfill and per-person month candidates (#2230, #2231)."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

from immich_memories.automation.backfill_detector import BackfillDetector
from immich_memories.automation.candidates import CandidateCategory, make_manual_memory_key
from immich_memories.automation.person_detectors import PersonMonthlyDetector

TODAY = date(2026, 10, 7)


def _month_key(year: int, month: int) -> str:
    last = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)).day
    return make_manual_memory_key(
        "monthly_highlights", date(year, month, 1), date(year, month, last)
    )


class TestBackfill:
    def test_proposes_quiet_months_of_this_year_and_last_newest_first(self):
        months = {"2026-08": 60, "2026-03": 40, "2025-11": 35}

        detection = BackfillDetector().detect(months, set(), TODAY)

        assert [c.date_range_start for c in detection.candidates] == [
            date(2026, 8, 1),
            date(2026, 3, 1),
            date(2025, 11, 1),
        ]
        first = detection.candidates[0]
        assert first.category is CandidateCategory.BACKFILL
        assert first.memory_type == "monthly_backfill"
        assert first.score == 0.35
        assert first.memory_key == _month_key(2026, 8)

    def test_the_latest_completed_month_is_the_monthly_detectors(self):
        detection = BackfillDetector().detect({"2026-09": 90, "2026-08": 90}, set(), TODAY)

        assert [c.date_range_start for c in detection.candidates] == [date(2026, 8, 1)]

    def test_a_month_already_filmed_by_hand_is_not_proposed(self):
        detection = BackfillDetector().detect({"2026-08": 90}, {_month_key(2026, 8)}, TODAY)

        assert detection.candidates == []

    def test_months_before_last_year_and_thin_months_are_left_out(self):
        months = {"2024-12": 500, "2026-07": 19}

        assert BackfillDetector().detect(months, set(), TODAY).candidates == []

    def test_a_month_another_detector_already_proposed_is_not_proposed_twice(self):
        detection = BackfillDetector().detect(
            {"2026-08": 90},
            set(),
            TODAY,
            proposed_keys={"monthly_highlights:2026-08-01:2026-08-31:"},
        )

        assert detection.candidates == []


def _person(pid: str = "p1", name: str = "Kid A"):
    return SimpleNamespace(id=pid, name=name)


def _days(month_start: date, count: int, distinct: int) -> dict[date, int]:
    per_day, extra = divmod(count, distinct)
    return {
        month_start + timedelta(days=i): per_day + (1 if i < extra else 0) for i in range(distinct)
    }


class TestPersonMonthly:
    def test_proposes_last_months_film_for_a_close_person(self):
        days = {"p1": _days(date(2026, 9, 1), 30, 6)}

        detection = PersonMonthlyDetector().detect([_person()], {"p1"}, days, set(), TODAY)

        (candidate,) = detection.candidates
        assert candidate.category is CandidateCategory.PERSON_MONTHLY
        assert candidate.memory_type == "person_monthly"
        assert candidate.person_names == ["Kid A"]
        assert candidate.score == 0.6
        assert (candidate.date_range_start, candidate.date_range_end) == (
            date(2026, 9, 1),
            date(2026, 9, 30),
        )
        # The key `generate --memory-type monthly_highlights --person "Kid A"` records.
        assert candidate.memory_key == make_manual_memory_key(
            "monthly_highlights", date(2026, 9, 1), date(2026, 9, 30), ["Kid A"]
        )

    def test_only_close_people_get_a_month(self):
        days = {"p1": _days(date(2026, 9, 1), 30, 6)}

        detection = PersonMonthlyDetector().detect([_person()], set(), days, set(), TODAY)

        assert detection.candidates == []

    def test_needs_fifteen_pictures_over_four_days(self):
        few = PersonMonthlyDetector().detect(
            [_person()], {"p1"}, {"p1": _days(date(2026, 9, 1), 14, 5)}, set(), TODAY
        )
        one_afternoon = PersonMonthlyDetector().detect(
            [_person()], {"p1"}, {"p1": _days(date(2026, 9, 1), 40, 3)}, set(), TODAY
        )

        assert few.candidates == [] and one_afternoon.candidates == []
        assert "15 pictures" in few.notes[0]
        assert "4 days" in one_afternoon.notes[0]

    def test_backfills_the_three_months_before_with_the_backfill_score(self):
        days = {
            "p1": {
                **_days(date(2026, 9, 1), 30, 6),
                **_days(date(2026, 7, 1), 30, 6),
                **_days(date(2026, 5, 1), 30, 6),
            }
        }

        detection = PersonMonthlyDetector().detect([_person()], {"p1"}, days, set(), TODAY)

        assert [(c.date_range_start.month, c.score) for c in detection.candidates] == [
            (9, 0.6),
            (7, 0.35),
        ]

    def test_a_month_filmed_by_hand_counts_as_made(self):
        made = make_manual_memory_key(
            "monthly_highlights", date(2026, 9, 1), date(2026, 9, 30), ["Kid A"]
        )

        detection = PersonMonthlyDetector().detect(
            [_person()], {"p1"}, {"p1": _days(date(2026, 9, 1), 30, 6)}, {made}, TODAY
        )

        assert detection.candidates == []


def test_a_month_an_automatic_monthly_run_made_is_not_backfilled():
    # What MonthlyDetector's own auto run leaves behind: plain dates.
    made_by_auto = {"monthly_highlights:2026-08-01:2026-08-31:"}

    assert BackfillDetector().detect({"2026-08": 90}, made_by_auto, TODAY).candidates == []
