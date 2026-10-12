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


# Pictures per day on 13, 14, 15, 16 and 17 August, in the shape of a real twenty-year library:
# busy days around the holiday most years, and the 15th itself standing out in some of them.
AUGUST = {
    2007: (42, 13, 5, 27, 0),
    2008: (59, 74, 0, 0, 4),
    2015: (3, 2, 33, 27, 41),
    2016: (18, 17, 13, 52, 24),
    2019: (23, 8, 11, 19, 10),
    2020: (59, 6, 11, 37, 9),
    2021: (26, 135, 4, 8, 12),
    2022: (243, 5, 99, 10, 16),
    2023: (14, 32, 9, 14, 14),
    2024: (205, 126, 174, 32, 43),
    2025: (7, 25, 33, 57, 105),
    2026: (23, 26, 71, 18, 15),
}


def _days_around(per_year: dict[int, tuple[int, ...]], month: int, day: int):
    """Pictures per day in the plus or minus two day window around an MM-DD, per year."""
    windows = {}
    for year, counts in per_year.items():
        centre = date(year, month, day)
        window = (centre - timedelta(days=2), centre + timedelta(days=2))
        windows[window] = {
            centre + timedelta(days=offset): n
            for offset, n in zip(range(-2, 3), counts, strict=True)
            if n
        }
    return windows


def _kept(years, month: int = 6, day: int = 21, on_the_day: int = 30):
    """A day kept in each of `years`: many pictures on it, a few on the days around."""
    return _days_around(dict.fromkeys(years, (2, 3, on_the_day, 3, 2)), month, day)


class TestHoliday:
    def test_a_day_that_stands_out_in_enough_years_is_proposed_across_every_year(self):
        # The Assumption is a public holiday in Belgium; the library keeps it in four years.
        today = date(2026, 8, 20)

        detection = HolidayDetector().detect(today, "BE", [], set(), _days_around(AUGUST, 8, 15))

        (candidate,) = [c for c in detection.candidates if c.date_range_end == date(2026, 8, 17)]
        assert candidate.category is CandidateCategory.HOLIDAY
        assert candidate.extra_params["marked_years"] == [2015, 2022, 2024, 2026]
        assert candidate.extra_params["year"] == 2026
        # The same window `generate --memory-type holiday --year 2026` records: every year.
        assert candidate.date_range_start == date(1997, 8, 13)
        assert candidate.memory_key == make_manual_memory_key(
            "holiday", date(1997, 8, 13), date(2026, 8, 17)
        )
        assert "stands out in 4 years" in candidate.reason

    def test_busy_days_around_a_quiet_holiday_never_qualify(self):
        # Two hundred pictures a year around the 15th, but never on it: a summer, not a holiday.
        busy = dict.fromkeys(range(2015, 2027), (80, 60, 8, 70, 90))

        detection = HolidayDetector().detect(
            date(2026, 8, 20), "BE", [], set(), _days_around(busy, 8, 15)
        )

        assert detection.candidates == []
        assert "stands out in 3 years" in detection.notes[0]

    def test_the_date_alone_never_qualifies(self):
        # Christmas is kept by default, but no picture shows it was.
        detection = HolidayDetector().detect(date(2026, 1, 5), None, [], set(), {})

        assert detection.candidates == []

    def test_a_celebrated_holiday_needs_no_home_country(self):
        detection = HolidayDetector().detect(
            date(2026, 1, 5), None, [], set(), _kept((2023, 2024, 2025), 12, 25)
        )

        (candidate,) = detection.candidates
        assert candidate.extra_params["holiday"] == "christmas"

    def test_an_extra_holiday_is_proposed_when_the_pictures_keep_it(self):
        today = date(2026, 6, 26)

        detection = HolidayDetector().detect(
            today, "US", ["06-21: Midsummer"], set(), _kept((2026, 2024, 2023))
        )

        (candidate,) = detection.candidates
        assert candidate.extra_params["holiday"] == "06-21"
        assert "Midsummer" in candidate.reason

    def test_two_years_that_kept_it_are_not_enough(self):
        detection = HolidayDetector().detect(
            date(2026, 6, 26), "US", ["06-21: Midsummer"], set(), _kept((2026, 2025))
        )

        assert detection.candidates == []

    def test_a_handful_of_pictures_on_a_quiet_week_is_not_a_kept_day(self):
        detection = HolidayDetector().detect(
            date(2026, 6, 26),
            "US",
            ["06-21: Midsummer"],
            set(),
            _kept((2026, 2025, 2024, 2023), on_the_day=6),
        )

        assert detection.candidates == []

    def test_waits_three_days_after_the_holiday(self):
        early = HolidayDetector().detect(
            date(2026, 6, 23), "US", ["06-21: Midsummer"], set(), _kept((2026, 2025, 2024))
        )

        assert early.candidates == []

    def test_a_film_made_by_hand_counts_as_made(self):
        made = make_manual_memory_key("holiday", date(1997, 6, 19), date(2026, 6, 23))

        detection = HolidayDetector().detect(
            date(2026, 6, 26), "US", ["06-21: Midsummer"], {made}, _kept((2026, 2025, 2024))
        )

        assert detection.candidates == []

    def test_a_film_of_fewer_years_still_counts_as_made_for_its_occurrence(self):
        # Made over five years, before a holiday film read every year: the occurrence is filmed.
        made = make_manual_memory_key("holiday", date(2022, 6, 19), date(2026, 6, 23))

        detection = HolidayDetector().detect(
            date(2026, 6, 26), "US", ["06-21: Midsummer"], {made}, _kept((2026, 2025, 2024))
        )

        assert detection.candidates == []

    def test_the_countrys_public_holidays_are_proposed_by_the_name_generate_accepts(self):
        # Thanksgiving is the US's own.
        today = date(2025, 12, 1)
        due = HolidayDetector().due(today, "US", [], set())
        thanksgiving = next(d for d in due if d.name == "Thanksgiving Day")
        days = {
            thanksgiving.window_of(day): {day: 40, day - timedelta(days=1): 4}
            for day in thanksgiving.days[:4]
        }

        detection = HolidayDetector().detect(today, "US", [], set(), days)

        names = {c.extra_params["holiday"] for c in detection.candidates}
        assert names == {"Thanksgiving Day"}

    def test_a_holiday_older_than_a_year_is_not_proposed(self):
        detection = HolidayDetector().detect(
            date(2026, 6, 23), "US", ["06-21: Midsummer"], set(), _kept((2025, 2024, 2023))
        )

        # 2025's midsummer is a year and two days old: this year's is not yet three days past.
        assert detection.candidates == []
