"""Season and holiday candidates (#2227, #2228)."""

from __future__ import annotations

from datetime import date, timedelta

from immich_memories.automation.candidates import CandidateCategory, make_manual_memory_key
from immich_memories.automation.season_holiday_detectors import HolidayDetector, SeasonDetector

SUMMER = (date(2025, 6, 1), date(2025, 8, 31))


def _days(count: int, distinct: int) -> dict[date, int]:
    per_day, extra = divmod(count, distinct)
    return {
        date(2025, 7, 1) + timedelta(days=i): per_day + (1 if i < extra else 0)
        for i in range(distinct)
    }


class TestSeason:
    def test_proposes_the_season_that_ended_three_days_ago(self):
        detection = SeasonDetector().detect(
            date(2025, 9, 3), "north", set(), {SUMMER: _days(60, 8)}
        )

        (candidate,) = detection.candidates
        assert candidate.category is CandidateCategory.SEASON
        assert candidate.memory_type == "season"
        assert (candidate.date_range_start, candidate.date_range_end) == SUMMER
        assert candidate.asset_count == 60
        assert candidate.extra_params["season"] == "summer"
        assert candidate.extra_params["hemisphere"] == "north"

    def test_waits_until_three_days_after_the_end(self):
        assert SeasonDetector().due(date(2025, 9, 2), "north", set()) is None

    def test_gives_up_thirty_days_after_the_end(self):
        assert SeasonDetector().due(date(2025, 9, 30), "north", set()) is not None
        assert SeasonDetector().due(date(2025, 10, 1), "north", set()) is None

    def test_the_southern_summer_is_the_one_that_ends_in_february(self):
        due = SeasonDetector().due(date(2026, 3, 5), "south", set())

        assert due is not None
        assert (due.start, due.end) == (date(2025, 12, 1), date(2026, 2, 28))
        assert due.season == "summer"

    def test_no_home_base_means_no_season_and_says_why(self):
        detection = SeasonDetector().detect(date(2025, 9, 3), None, set(), {})

        assert detection.candidates == []
        assert "home base" in detection.notes[0]

    def test_a_season_filmed_by_hand_is_not_proposed_again(self):
        made = make_manual_memory_key("season", *SUMMER)

        assert SeasonDetector().due(date(2025, 9, 3), "north", {made}) is None

    def test_needs_forty_pictures_over_six_days(self):
        thin = SeasonDetector().detect(date(2025, 9, 3), "north", set(), {SUMMER: _days(39, 8)})
        short = SeasonDetector().detect(date(2025, 9, 3), "north", set(), {SUMMER: _days(80, 5)})

        assert thin.candidates == [] and short.candidates == []
        assert "40 pictures" in thin.notes[0]
        assert "6 days" in short.notes[0]


def _windows(centre_per_year: dict[int, int], month: int, day: int) -> dict[tuple[date, date], int]:
    """Pictures in the plus or minus two day window around an MM-DD, per year."""
    return {
        (date(y, month, day) - timedelta(days=2), date(y, month, day) + timedelta(days=2)): n
        for y, n in centre_per_year.items()
    }


class TestHoliday:
    def test_proposes_a_holiday_across_every_year_with_material(self):
        # Midsummer, kept by this library as an extra holiday.
        today = date(2026, 6, 26)
        pictures = _windows({2026: 30, 2025: 12, 2024: 0, 2023: 9, 2022: 4}, 6, 21)

        detection = HolidayDetector().detect(today, "US", ["06-21: Midsummer"], set(), pictures)

        (candidate,) = detection.candidates
        assert candidate.category is CandidateCategory.HOLIDAY
        assert candidate.memory_type == "holiday"
        assert candidate.asset_count == 55
        assert candidate.extra_params["holiday"] == "06-21"
        assert candidate.extra_params["year"] == 2026
        # The same window `generate --memory-type holiday --year 2026` records: five years.
        assert (candidate.date_range_start, candidate.date_range_end) == (
            date(2022, 6, 19),
            date(2026, 6, 23),
        )
        assert candidate.memory_key == make_manual_memory_key(
            "holiday", date(2022, 6, 19), date(2026, 6, 23)
        )
        assert "Midsummer" in candidate.reason

    def test_waits_three_days_after_the_holiday(self):
        pictures = _windows({2026: 30, 2025: 30}, 6, 21)

        early = HolidayDetector().detect(
            date(2026, 6, 23), "US", ["06-21: Midsummer"], set(), pictures
        )

        assert early.candidates == []

    def test_one_year_of_material_is_not_a_film_across_years(self):
        pictures = _windows({2026: 60, 2025: 0}, 6, 21)

        detection = HolidayDetector().detect(
            date(2026, 6, 26), "US", ["06-21: Midsummer"], set(), pictures
        )

        assert detection.candidates == []

    def test_fewer_than_twenty_pictures_is_not_a_film(self):
        pictures = _windows({2026: 5, 2025: 6}, 6, 21)

        detection = HolidayDetector().detect(
            date(2026, 6, 26), "US", ["06-21: Midsummer"], set(), pictures
        )

        assert detection.candidates == []

    def test_a_film_made_by_hand_counts_as_made(self):
        pictures = _windows({2026: 30, 2025: 30}, 6, 21)
        made = make_manual_memory_key("holiday", date(2022, 6, 19), date(2026, 6, 23))

        detection = HolidayDetector().detect(
            date(2026, 6, 26), "US", ["06-21: Midsummer"], {made}, pictures
        )

        assert detection.candidates == []

    def test_the_countrys_public_holidays_are_proposed_by_the_name_generate_accepts(self):
        # Thanksgiving is the US's own.
        today = date(2025, 12, 1)
        due = HolidayDetector().due(today, "US", [], set())
        pictures = {w: 40 for d in due for w in d.windows}

        detection = HolidayDetector().detect(today, "US", [], set(), pictures)

        names = {c.extra_params["holiday"] for c in detection.candidates}
        assert "Thanksgiving Day" in names

    def test_a_holiday_older_than_a_year_is_not_proposed(self):
        pictures = _windows({2025: 30, 2024: 30}, 6, 21)

        detection = HolidayDetector().detect(
            date(2026, 6, 23), "US", ["06-21: Midsummer"], set(), pictures
        )

        # 2025's midsummer is a year and two days old: this year's is not yet three days past.
        assert detection.candidates == []

    def test_no_country_still_proposes_the_extra_holidays(self):
        pictures = _windows({2026: 30, 2025: 30}, 6, 21)

        detection = HolidayDetector().detect(
            date(2026, 6, 26), None, ["06-21: Midsummer"], set(), pictures
        )

        assert len(detection.candidates) == 1
