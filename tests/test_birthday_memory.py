"""A birthday film runs birthday to birthday, whatever month it is today.

Two films, never mixed. The birthday film is the rolling year that ends on the
birthday being celebrated, and nothing else. Asked for with years back, the
birthdays film is that birthday and each earlier one, ±1 day, and no rolling
year. Nothing here may depend on which calendar year the request happened to name.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from immich_memories.automation.calendar_detectors import BirthdayDetector
from immich_memories.automation.generation_request import GenerationRequest
from immich_memories.cli._asset_fetch import fetch_videos
from immich_memories.cli._date_resolution import resolve_date_range
from immich_memories.cli._helpers import set_active_display
from immich_memories.memory_types.date_builders import (
    BIRTHDAY_HISTORY_FROM,
    birthday_anchor,
    build_birthday_windows,
)
from immich_memories.memory_types.factory import create_preset
from immich_memories.memory_types.registry import MemoryType
from immich_memories.planning.memory_length import default_duration_for_type
from immich_memories.timeperiod import DateRange


class TestRollingYear:
    """The recent window is the year from the previous birthday through the one celebrated."""

    def test_february_birthday_runs_february_to_february(self):
        """The bug that named the issue: a 7 February birthday, a July window.

        The window used to be picked by a calendar year number and run forward
        from it, so the birthday the memory is named for fell outside it.
        """
        windows = build_birthday_windows(date(2018, 2, 7), year=2026)

        assert windows[0].start == datetime(2025, 2, 7)
        assert windows[0].end == datetime(2026, 2, 7, 23, 59, 59)

    def test_the_birthday_being_celebrated_is_inside_the_memory(self):
        windows = build_birthday_windows(date(2018, 2, 7), year=2026)

        assert windows[0].contains(datetime(2026, 2, 7, 12, 0))

    def test_the_previous_birthday_opens_the_memory(self):
        """A yearly review starting from the birthdate: last year's party is its first day."""
        windows = build_birthday_windows(date(2018, 2, 7), year=2026)

        assert windows[0].contains(datetime(2025, 2, 7, 12, 0))
        assert not windows[0].contains(datetime(2025, 2, 6, 12, 0))

    def test_no_year_celebrates_the_most_recent_birthday(self):
        """A run in August is still about February's birthday, not next year's."""
        windows = build_birthday_windows(date(2018, 2, 7), today=date(2026, 8, 25))

        assert windows[0].end == datetime(2026, 2, 7, 23, 59, 59)

    def test_a_run_on_the_birthday_itself_celebrates_it(self):
        windows = build_birthday_windows(date(2018, 2, 7), today=date(2026, 2, 7))

        assert windows[0].end == datetime(2026, 2, 7, 23, 59, 59)

    def test_the_cli_does_not_demand_a_year_for_a_birthday_memory(self):
        """Every other spotlight needs --year; this one knows which birthday."""
        windows = resolve_date_range(
            year=None,
            start=None,
            end=None,
            period=None,
            birthday="02-07",
            memory_type="person_spotlight",
        )

        assert isinstance(windows, list)
        assert windows[0].end.month == 2
        assert windows[0].end.day == 7


class TestTheBirthdayFilmIsTheYear:
    """A birthday film holds the year from one birthday to the next and no earlier birthday."""

    def test_a_birthday_film_is_the_rolling_year_alone(self):
        windows = build_birthday_windows(date(2018, 2, 7), year=2026)

        assert windows == [
            DateRange(start=datetime(2025, 2, 7), end=datetime(2026, 2, 7, 23, 59, 59))
        ]

    def test_no_years_back_is_the_same_film(self):
        assert build_birthday_windows(date(2018, 2, 7), year=2026, years_back=0) == (
            build_birthday_windows(date(2018, 2, 7), year=2026)
        )

    def test_the_cli_birthday_film_holds_nothing_from_earlier_years(self):
        windows = resolve_date_range(
            year=2026,
            start=None,
            end=None,
            period=None,
            birthday="08-30",
            memory_type="person_spotlight",
        )

        assert isinstance(windows, list)
        assert len(windows) == 1
        # The pictures of last year's party, on the 30th itself, are in the film.
        assert windows[0].start == datetime(2025, 8, 30)


class TestTheBirthdaysFilm:
    """Asked for with years back: the birthdays themselves, ±1 day, and nothing between."""

    def test_the_celebrated_birthday_and_each_earlier_one(self):
        windows = build_birthday_windows(date(2018, 2, 7), year=2026, years_back=3)

        assert [w.start.year for w in windows] == [2026, 2025, 2024, 2023]

    def test_every_window_is_the_birthday_plus_or_minus_a_day(self):
        windows = build_birthday_windows(date(2018, 2, 7), year=2026, years_back=3)

        assert windows[0].start == datetime(2026, 2, 6)
        assert windows[0].end == datetime(2026, 2, 8, 23, 59, 59)
        assert windows[BIRTHDAY_HISTORY_FROM].start == datetime(2025, 2, 6)
        assert windows[BIRTHDAY_HISTORY_FROM].end == datetime(2025, 2, 8, 23, 59, 59)
        assert all((w.end - w.start).days < 3 for w in windows)

    def test_no_rolling_year_comes_with_it(self):
        windows = build_birthday_windows(date(2018, 2, 7), year=2026, years_back=5)

        assert not any(w.contains(datetime(2025, 9, 1, 12, 0)) for w in windows)

    def test_the_display_span_reaches_from_the_oldest_birthday_to_the_newest(self):
        windows = build_birthday_windows(date(2018, 2, 7), year=2026, years_back=4)

        assert windows[-1].start == datetime(2022, 2, 6)
        assert windows[0].end == datetime(2026, 2, 8, 23, 59, 59)


class TestWhereTheBirthdayComesFrom:
    """Immich is the source of truth; a typed date is an override for one run."""

    def test_the_immich_birth_date_anchors_the_memory(self):
        assert birthday_anchor(datetime(2018, 2, 7, 0, 0), None, person_name="Ada") == date(
            2018, 2, 7
        )

    def test_a_typed_date_overrides_what_immich_holds(self):
        anchor = birthday_anchor(datetime(2018, 2, 7), date(2000, 11, 20), person_name="Ada")

        assert anchor == date(2000, 11, 20)

    def test_a_typed_date_still_answers_when_immich_holds_nothing(self):
        assert birthday_anchor(None, date(2000, 11, 20), person_name="Ada") == date(2000, 11, 20)

    def test_neither_is_an_error_that_says_where_to_set_it(self):
        """Refuse over fake: the error is how the user learns Immich drives this."""
        with pytest.raises(ValueError, match="People") as caught:
            birthday_anchor(None, None, person_name="Ada")

        assert "Ada" in str(caught.value)
        assert "birth date" in str(caught.value)


class _EmptyLibrary:
    """Stands in for the Immich HTTP API, which has nothing to offer.

    WHY: the only boundary the fetch crosses, and an empty library is what
    makes every history window report zero — which is the case under test.
    """

    def get_videos_for_date_range(self, _date_range) -> list:
        return []

    def get_photos_for_date_range(self, _date_range) -> list:
        return []


class _RecordingDisplay:
    """The terminal the CLI's print helpers write to, keeping what they said.

    WHY: set_active_display is the seam the helpers already route through, and
    it does not depend on which stdout the module-level Rich console bound to
    when it was imported — which is what made reading this back through capsys
    depend on test ordering.
    """

    def __init__(self) -> None:
        self.lines: list[str] = []

    def print_message(self, message: str) -> None:
        self.lines.append(message)

    def add_task(self, _description: str, **_fields) -> int:
        return 0

    def update(self, _task_id: int, **_kwargs) -> None:
        return None


class TestSparseHistoryReporting:
    """Five empty earlier birthdays are a library; an empty celebrated birthday is worth a warning."""

    def _report(self, *, history_from: int | None) -> str:
        display = _RecordingDisplay()
        set_active_display(display)
        try:
            fetch_videos(
                client=_EmptyLibrary(),
                progress=display,
                date_ranges=build_birthday_windows(date(2018, 2, 7), year=2026, years_back=5),
                person_ids=["person-ada"],
                history_from=history_from,
            )
        finally:
            set_active_display(None)
        return "\n".join(display.lines)

    def test_the_earlier_birthdays_are_summarised_rather_than_warned_about(self):
        out = self._report(history_from=BIRTHDAY_HISTORY_FROM)

        assert "history: 0 of 5 earlier windows hold material" in out

    def test_an_empty_celebrated_birthday_still_gets_its_own_warning(self):
        out = self._report(history_from=BIRTHDAY_HISTORY_FROM)

        assert "2026-02-06..2026-02-08" in out

    def test_without_the_mark_every_window_shouts(self):
        """The behaviour the mark exists to avoid, pinned so it stays avoided."""
        out = self._report(history_from=None)

        assert out.count("no videos found for") == 6


class _PhotoLibrary(_EmptyLibrary):
    """No videos anywhere; the photos it holds are returned for the window they fall in."""

    def __init__(self, photos: list) -> None:
        self.photos = photos

    def get_photos_for_date_range(self, date_range, progress_callback=None, **_people) -> list:
        return [p for p in self.photos if date_range.contains(p.file_created_at)]


class TestHistoryCountsPhotosToo:
    """A photo-rich library with no videos has history; the report must not say otherwise (#2041)."""

    def _report(self, photos: list) -> str:
        from immich_memories.cli._asset_fetch import fetch_media

        display = _RecordingDisplay()
        set_active_display(display)
        try:
            fetch_media(
                client=_PhotoLibrary(photos),
                progress=display,
                date_ranges=build_birthday_windows(date(2018, 2, 7), year=2026, years_back=5),
                person_ids=[],
                include_photos=True,
                history_from=BIRTHDAY_HISTORY_FROM,
            )
        finally:
            set_active_display(None)
        return "\n".join(display.lines)

    def test_a_photo_in_an_earlier_window_is_history(self):
        from tests.conftest import make_asset

        day_of_birth = make_asset("party", file_created_at=datetime(2024, 2, 7, 10, 0))

        out = self._report([day_of_birth])

        assert "history: 1 of 5 earlier windows hold material" in out
        assert "the memory has no history" not in out

    def test_a_library_with_nothing_in_any_earlier_window_still_warns(self):
        out = self._report([])

        assert "the memory has no history" in out
        assert "no photos and videos found for 2026-02-06..2026-02-08" in out


class TestAutomationRoundTrip:
    """What the nightly runner proposes is what the CLI it spawns renders."""

    def test_the_candidate_window_survives_the_argv(self):
        """--year names the celebrated birthday, so it must be read off the end.

        The detector picks a completed birthday year and hands the child
        process a year number; taking that from the start of the window would
        render the year before the one the runner proposed, silently.
        """
        person = SimpleNamespace(id="p1", name="Ada", birth_date=date(2000, 2, 7))

        # WHY: BirthdayDetector reads no config field on this path; the object
        # is only there to satisfy the signature.
        candidate = BirthdayDetector().detect(
            {}, [person], set(), MagicMock(), date(2026, 2, 20), person_asset_counts={"p1": 80}
        )[0]
        argv = GenerationRequest.from_candidate(candidate, upload=False).to_argv()
        year = int(argv[argv.index("--year") + 1])

        years_back = int(argv[argv.index("--years-back") + 1]) if "--years-back" in argv else None
        windows = build_birthday_windows(person.birth_date, year, years_back=years_back)
        assert len(windows) == 1
        rolling = windows[0]
        from immich_memories.automation.calendar_detectors import birthday_film_windows

        assert birthday_film_windows(person.birth_date, date(2026, 2, 20)) == windows

        assert rolling.start.date() == candidate.date_range_start
        assert rolling.end.date() == candidate.date_range_end


class TestLength:
    """The birthday film is a year long; the birthdays film is a few days across years."""

    def test_the_birthday_film_asks_for_ten_minutes(self):
        windows = build_birthday_windows(date(1990, 2, 7), year=2026)

        length = default_duration_for_type(
            "person_spotlight", windows[0], primary_window=windows[0]
        )

        assert length == pytest.approx(600.0)

    def test_the_birthdays_film_asks_for_a_holiday_length(self):
        """Its days would floor at 30 s on the span curve; a holiday's days ask for 60."""
        windows = build_birthday_windows(date(1990, 2, 7), year=2026, years_back=5)
        display = DateRange(start=windows[-1].start, end=windows[0].end)

        length = default_duration_for_type(
            "person_spotlight",
            display,
            {"birthday_years_back": 5},
            primary_window=windows[0],
        )

        assert length == pytest.approx(60.0)

    def test_the_presets_agree(self):
        year = create_preset(
            MemoryType.PERSON_SPOTLIGHT,
            year=2026,
            person_names=["Kit"],
            use_birthday=True,
            birthday=date(2018, 2, 7),
        )
        days = create_preset(
            MemoryType.PERSON_SPOTLIGHT,
            year=2026,
            person_names=["Kit"],
            use_birthday=True,
            birthday=date(2018, 2, 7),
            years_back=3,
        )

        assert (year.default_duration_seconds, len(year.date_ranges)) == (600, 1)
        assert (days.default_duration_seconds, len(days.date_ranges)) == (60, 4)


class TestLeapDay:
    """A 29 February birthday is celebrated on the 28th in an ordinary year."""

    def test_the_rolling_year_ends_on_the_twenty_eighth(self):
        windows = build_birthday_windows(date(2000, 2, 29), year=2026)

        assert windows[0].end == datetime(2026, 2, 28, 23, 59, 59)

    def test_a_leap_year_birthday_still_reaches_the_twenty_ninth(self):
        """±1 day around the 28th covers the 29th in the years that have one."""
        windows = build_birthday_windows(date(2000, 2, 29), year=2026, years_back=2)

        assert windows[-1].contains(datetime(2024, 2, 29, 12, 0))
