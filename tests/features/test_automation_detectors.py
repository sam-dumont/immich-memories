"""Feature tests: what each automation detector proposes in `auto suggest --json`.

Each library is built for one promise in docs-site/docs/reference/automation-contract.md
(the detector table), with a case just inside the promise's boundary and one just outside.
The real CLI runs against a picture-level Immich (tests/features/automation_library.py) on
a fixed day; people, saved groups and special days are set up with the commands a user
would use (`people import`, `people group add`, `days-import`).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest

from tests.features.automation_library import (
    Library,
    LocalHttp,
    cli,
    import_people,
    import_special_days,
    of_category,
    record_film,
    suggest_text,
    suggestions,
    write_config,
)


def _ranges(rows: list[dict]) -> list[str]:
    return [row["date_range"] for row in rows]


# ── yearly ───────────────────────────────────────────────────────────────


def _years_library() -> Library:
    return Library().month("2025-03", 30).month("2025-08", 40).month("2023-05", 20)


@pytest.mark.feature("detector.yearly")
def test_a_past_year_with_pictures_is_proposed_from_15_january(tmp_path: Path) -> None:
    rows = suggestions(write_config(tmp_path), _years_library(), date(2026, 1, 15))

    years = _ranges(of_category(rows, "year_in_review"))
    assert "2025-01-01 to 2025-12-31" in years
    assert "2023-01-01 to 2023-12-31" in years
    # A year with no pictures is not a year to review.
    assert "2024-01-01 to 2024-12-31" not in years


@pytest.mark.feature("detector.yearly")
def test_the_year_just_ended_waits_until_15_january(tmp_path: Path) -> None:
    rows = suggestions(write_config(tmp_path), _years_library(), date(2026, 1, 14))

    years = _ranges(of_category(rows, "year_in_review"))
    assert "2025-01-01 to 2025-12-31" not in years
    assert "2023-01-01 to 2023-12-31" in years


# ── birthday ─────────────────────────────────────────────────────────────

BORN = date(2015, 3, 10)
BIRTHDAY_FILM = "2025-03-11 to 2026-03-10"


def _birthday_library(pictures: int = 50, days: int = 3) -> Library:
    """A child whose year up to the 2026 birthday holds ``pictures`` over ``days`` days."""
    library = Library().person("p-kid", "Kid", birth=BORN)
    party_days = [date(2025, 7, 1), date(2025, 12, 24), date(2026, 3, 10)][:days]
    for index in range(pictures):
        library.on(party_days[index % days], 1, ("p-kid",))
    return library


@pytest.mark.feature("detector.birthday")
@pytest.mark.parametrize("today", [date(2026, 3, 12), date(2026, 5, 9)], ids=["2-days", "60-days"])
def test_a_birthday_2_to_60_days_ago_is_proposed(tmp_path: Path, today: date) -> None:
    rows = suggestions(write_config(tmp_path), _birthday_library(), today)

    birthdays = of_category(rows, "birthday")
    assert _ranges(birthdays) == [BIRTHDAY_FILM]
    assert birthdays[0]["person_names"] == ["Kid"]
    assert birthdays[0]["reason"].startswith("Birthday (11 years old)")


@pytest.mark.feature("detector.birthday")
@pytest.mark.parametrize("today", [date(2026, 3, 11), date(2026, 5, 10)], ids=["1-day", "61-days"])
def test_a_birthday_outside_2_to_60_days_is_not_proposed(tmp_path: Path, today: date) -> None:
    rows = suggestions(write_config(tmp_path), _birthday_library(), today)

    assert of_category(rows, "birthday") == []


@pytest.mark.feature("detector.birthday")
def test_a_birthday_under_50_pictures_says_why_instead(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    today = date(2026, 3, 12)

    rows = suggestions(config, _birthday_library(pictures=49), today)
    printed = suggest_text(config, _birthday_library(pictures=49), today)

    assert of_category(rows, "birthday") == []
    assert "No birthday film for Kid: 49 pictures, it needs 50" in printed


@pytest.mark.feature("detector.birthday")
def test_a_birthday_on_two_days_says_why_instead(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    today = date(2026, 3, 12)

    rows = suggestions(config, _birthday_library(pictures=60, days=2), today)
    printed = suggest_text(config, _birthday_library(pictures=60, days=2), today)

    assert of_category(rows, "birthday") == []
    assert "No birthday film for Kid: 60 pictures over 2 days, it needs 3 days" in printed


# ── monthly ──────────────────────────────────────────────────────────────


@pytest.mark.feature("detector.monthly")
def test_the_latest_completed_month_is_proposed_and_no_earlier_one(tmp_path: Path) -> None:
    library = Library().month("2026-05", 80).month("2026-04", 60).month("2026-03", 70)

    rows = suggestions(write_config(tmp_path), library, date(2026, 6, 10))

    assert _ranges(of_category(rows, "monthly_review")) == ["2026-05-01 to 2026-05-31"]


@pytest.mark.feature("detector.monthly")
def test_an_empty_last_month_is_not_replaced_by_an_earlier_one(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    library = Library().month("2026-04", 60)

    rows = suggestions(config, library, date(2026, 6, 10))
    printed = suggest_text(config, library, date(2026, 6, 10))

    assert of_category(rows, "monthly_review") == []
    assert "No month film: the last completed month has no pictures" in printed


@pytest.mark.feature("detector.monthly")
def test_a_month_that_has_its_film_is_not_proposed_again(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    record_film(
        config,
        "monthly_highlights",
        "monthly_highlights:2026-05-01:2026-05-31:",
        source="auto",
        category="monthly_review",
    )

    rows = suggestions(config, Library().month("2026-05", 80), date(2026, 6, 10))

    assert of_category(rows, "monthly_review") == []


@pytest.mark.feature("detector.monthly")
def test_the_month_in_progress_is_not_the_monthly_film(tmp_path: Path) -> None:
    library = Library().month("2026-06", 80)

    rows = suggestions(write_config(tmp_path), library, date(2026, 6, 28))

    assert of_category(rows, "monthly_review") == []


# ── activity burst ───────────────────────────────────────────────────────


def _steady_year_then(burst: int) -> Library:
    """Twelve months of 50 pictures to August 2026, ``burst`` in September, 50 in October."""
    library = Library()
    first = date(2025, 9, 1)
    for offset in range(12):
        month = date(
            first.year + (first.month + offset - 1) // 12, (first.month + offset - 1) % 12 + 1, 1
        )
        library.month(f"{month:%Y-%m}", 50)
    return library.month("2026-09", burst).month("2026-10", 50)


@pytest.mark.feature("detector.activity-burst")
def test_a_month_over_twice_the_rolling_average_is_proposed(tmp_path: Path) -> None:
    rows = suggestions(write_config(tmp_path), _steady_year_then(101), date(2026, 11, 10))

    bursts = of_category(rows, "activity_burst")
    assert _ranges(bursts) == ["2026-09-01 to 2026-09-30"]
    assert bursts[0]["reason"].startswith("2.0x average activity (101 assets vs 50 avg)")


@pytest.mark.feature("detector.activity-burst")
def test_a_month_at_exactly_twice_the_average_is_not_a_burst(tmp_path: Path) -> None:
    rows = suggestions(write_config(tmp_path), _steady_year_then(100), date(2026, 11, 10))

    assert of_category(rows, "activity_burst") == []


# ── person spotlight ─────────────────────────────────────────────────────


def _six_people() -> Library:
    """Six named people pictured 60, 50, 40, 30, 20 and 10 times last year."""
    library = Library()
    for rank, count in enumerate((60, 50, 40, 30, 20, 10), start=1):
        person = f"p-{rank}"
        library.person(person, f"Person {rank}").across(date(2025, 2, 1), 10, count, (person,))
    return library


@pytest.mark.feature("detector.person-spotlight")
def test_the_five_most_pictured_people_are_proposed(tmp_path: Path) -> None:
    from immich_memories.automation.candidates import make_memory_key

    config = write_config(tmp_path)
    # Suggest shows three films of a type at most; with the top three filmed already,
    # what is left of the five shows, and the sixth person never does.
    for rank in (1, 2, 3):
        record_film(
            config,
            "person_spotlight",
            make_memory_key(
                "person_spotlight", date(2025, 1, 1), date(2025, 12, 31), [f"person {rank}"]
            ),
        )

    rows = suggestions(config, _six_people(), date(2026, 3, 1))

    spotlights = of_category(rows, "person_spotlight")
    assert [row["person_names"] for row in spotlights] == [["Person 4"], ["Person 5"]]
    assert {row["date_range"] for row in spotlights} == {"2025-01-01 to 2025-12-31"}


@pytest.mark.feature("detector.person-spotlight")
def test_the_three_most_pictured_lead_the_list(tmp_path: Path) -> None:
    rows = suggestions(write_config(tmp_path), _six_people(), date(2026, 3, 1))

    spotlights = of_category(rows, "person_spotlight")
    assert [row["person_names"] for row in spotlights] == [["Person 1"], ["Person 2"], ["Person 3"]]


@pytest.mark.feature("detector.person-spotlight")
def test_a_close_person_outranks_an_acquaintance_with_as_many_pictures(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    library = Library()
    for person, name in (("p-close", "Close"), ("p-met", "Met")):
        library.person(person, name).across(date(2025, 2, 1), 10, 40, (person,))
    import_people(config, {"p-close": ("Close", "inner"), "p-met": ("Met", "episodic")})

    rows = suggestions(config, library, date(2026, 3, 1))

    spotlights = {
        row["person_names"][0]: row["score"] for row in of_category(rows, "person_spotlight")
    }
    assert spotlights["Close"] > spotlights["Met"]


# ── multi-person ─────────────────────────────────────────────────────────


def _a_pair_together(shared: int) -> Library:
    """Two people, each with 120 pictures last year, ``shared`` of them together."""
    library = Library().person("p-a", "Alex").person("p-b", "Billie")
    library.across(date(2025, 4, 1), 20, shared, ("p-a", "p-b"))
    library.across(date(2025, 6, 1), 20, 120 - shared, ("p-a",))
    return library.across(date(2025, 8, 1), 20, 120 - shared, ("p-b",))


@pytest.mark.feature("detector.multi-person")
def test_a_pair_together_on_10_pictures_last_year_is_proposed(tmp_path: Path) -> None:
    rows = suggestions(write_config(tmp_path), _a_pair_together(10), date(2026, 3, 1))

    pairs = of_category(rows, "multi_person")
    assert [row["person_names"] for row in pairs] == [["Alex", "Billie"]]
    assert pairs[0]["date_range"] == "2025-01-01 to 2025-12-31"


@pytest.mark.feature("detector.multi-person")
def test_a_pair_together_on_9_pictures_last_year_is_not_proposed(tmp_path: Path) -> None:
    rows = suggestions(write_config(tmp_path), _a_pair_together(9), date(2026, 3, 1))

    assert of_category(rows, "multi_person") == []


# ── on this day ──────────────────────────────────────────────────────────


def _march_in(*years: int) -> Library:
    library = Library()
    for year in years:
        library.month(f"{year}-03", 30)
    return library


@pytest.mark.feature("detector.on-this-day")
def test_today_is_proposed_when_its_month_has_pictures_in_five_prior_years(
    tmp_path: Path,
) -> None:
    library = _march_in(2021, 2022, 2023, 2024, 2025)

    rows = suggestions(write_config(tmp_path), library, date(2026, 3, 12))

    days = of_category(rows, "on_this_day")
    assert _ranges(days) == ["2026-03-12 to 2026-03-12"]
    assert days[0]["source_years"] == [2021, 2022, 2023, 2024, 2025]


@pytest.mark.feature("detector.on-this-day")
def test_four_prior_years_are_not_enough(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    library = _march_in(2022, 2023, 2024, 2025, 2026)

    rows = suggestions(config, library, date(2026, 3, 12))
    printed = suggest_text(config, library, date(2026, 3, 12))

    assert of_category(rows, "on_this_day") == []
    assert "this month has pictures in 4 prior years; it needs 5" in printed


# ── special day ──────────────────────────────────────────────────────────


@pytest.mark.feature("detector.special-day")
def test_the_roundest_anniversary_within_three_days_is_proposed_first(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    import_special_days(
        config,
        (date(2019, 3, 12), 40),  # seventh anniversary, today
        (date(2021, 3, 10), 40),  # fifth, two days ago
        (date(2016, 3, 15), 40),  # tenth, in three days
    )

    rows = suggestions(config, Library().month("2026-02", 30), date(2026, 3, 12))

    special = of_category(rows, "emergent_day")
    assert _ranges(special)[0] == "2016-03-15 to 2016-03-15"
    assert special[0]["reason"].startswith("10 years ago")


@pytest.mark.feature("detector.special-day")
def test_an_anniversary_four_days_away_is_not_proposed(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    import_special_days(config, (date(2016, 3, 16), 40), (date(2018, 3, 8), 40))

    rows = suggestions(config, Library().month("2026-02", 30), date(2026, 3, 12))
    printed = suggest_text(config, Library().month("2026-02", 30), date(2026, 3, 12))

    assert of_category(rows, "emergent_day") == []
    assert "No special day film: no unfilmed anniversary is within three days of today" in printed


# ── saved group ──────────────────────────────────────────────────────────


def _a_family_last_year() -> Library:
    library = Library().person("p-kid", "Kid").person("p-pal", "Pal")
    library.across(date(2025, 4, 1), 10, 30, ("p-kid", "p-pal"))
    return library.across(date(2025, 9, 1), 10, 30, ("p-kid",))


def _family_rows(rows: list[dict]) -> list[dict]:
    return [r for r in of_category(rows, "multi_person") if "Saved group 'family'" in r["reason"]]


@pytest.mark.feature("detector.saved-group")
def test_a_saved_group_is_proposed_last_years_film(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    added = cli(config, "people", "group", "add", "family", '"p-kid" OR "p-pal"')
    assert added.exit_code == 0, added.output

    rows = suggestions(config, _a_family_last_year(), date(2026, 3, 1))

    assert _ranges(_family_rows(rows)) == ["2025-01-01 to 2025-12-31"]


@pytest.mark.feature("detector.saved-group")
def test_a_saved_group_film_is_proposed_once(tmp_path: Path) -> None:
    from unittest.mock import patch

    from tests.auto_library_fake import FakeGenerateChild
    from tests.features.automation_library import immich_holding, today_is

    config = write_config(tmp_path)
    cli(config, "people", "group", "add", "family", '"p-kid" OR "p-pal"')
    key = _family_rows(suggestions(config, _a_family_last_year(), date(2026, 3, 1)))[0][
        "memory_key"
    ]
    child = FakeGenerateChild(tmp_path / "films")
    # WHY: the `generate` child process; the stand-in records the group's film.
    with (
        immich_holding(_a_family_last_year()),
        today_is(date(2026, 3, 1)),
        patch("immich_memories.automation.runner._execute_generate", child),
    ):
        made = cli(config, "auto", "run", "--candidate", key)
    assert made.exit_code == 0, made.output

    rows = suggestions(config, _a_family_last_year(), date(2026, 3, 2))

    assert len(child.commands) == 1
    assert _family_rows(rows) == []


@pytest.mark.feature("detector.saved-group")
def test_a_saved_group_with_no_pictures_last_year_is_skipped(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    cli(config, "people", "group", "add", "family", '"p-kid" OR "p-pal"')
    library = Library().person("p-kid", "Kid").person("p-pal", "Pal").person("p-x", "Other")
    library.across(date(2024, 4, 1), 10, 30, ("p-kid", "p-pal"))
    library.across(date(2025, 4, 1), 10, 30, ("p-x",))

    rows = suggestions(config, library, date(2026, 3, 1))

    assert _family_rows(rows) == []


# ── season ───────────────────────────────────────────────────────────────


@pytest.fixture
def immich_geodata() -> Iterator[LocalHttp]:
    """Immich's reverse geocoder: the home base is in Belgium."""
    server = LocalHttp({"/api/map/reverse-geocode": [{"country": "Belgium", "city": "Brussels"}]})
    yield server
    server.close()


def _a_summer() -> Library:
    """40 pictures over six July days."""
    return Library().across(date(2026, 7, 1), 6, 40)


@pytest.mark.feature("detector.season")
@pytest.mark.parametrize("today", [date(2026, 9, 3), date(2026, 9, 30)], ids=["3-days", "30-days"])
def test_the_season_that_ended_3_to_30_days_ago_is_proposed(
    tmp_path: Path, immich_geodata: LocalHttp, today: date
) -> None:
    config = write_config(tmp_path, immich_url=immich_geodata.url, home_base=True)

    rows = suggestions(config, _a_summer(), today)

    seasons = of_category(rows, "season")
    assert _ranges(seasons) == ["2026-06-01 to 2026-08-31"]
    assert seasons[0]["reason"].startswith("Summer just ended, 40 pictures over 6 days")


@pytest.mark.feature("detector.season")
@pytest.mark.parametrize("today", [date(2026, 9, 2), date(2026, 10, 1)], ids=["2-days", "31-days"])
def test_a_season_outside_3_to_30_days_is_not_proposed(
    tmp_path: Path, immich_geodata: LocalHttp, today: date
) -> None:
    config = write_config(tmp_path, immich_url=immich_geodata.url, home_base=True)

    rows = suggestions(config, _a_summer(), today)

    assert of_category(rows, "season") == []


@pytest.mark.feature("detector.season")
def test_without_a_home_base_there_is_no_season_film(tmp_path: Path) -> None:
    config = write_config(tmp_path)

    rows = suggestions(config, _a_summer(), date(2026, 9, 3))
    printed = suggest_text(config, _a_summer(), date(2026, 9, 3))

    assert of_category(rows, "season") == []
    assert "No season film: the home base is not set" in printed


# ── holiday ──────────────────────────────────────────────────────────────


def _national_days() -> Library:
    """Ten pictures on each of the last three Belgian National Days (21 July), none around."""
    return Library().on(date(2025, 7, 21), 10).on(date(2024, 7, 21), 10).on(date(2023, 7, 21), 10)


@pytest.mark.feature("detector.holiday")
def test_a_home_country_holiday_is_proposed_from_3_days_after_it(
    tmp_path: Path, immich_geodata: LocalHttp
) -> None:
    config = write_config(tmp_path, immich_url=immich_geodata.url, home_base=True)

    rows = suggestions(config, _national_days(), date(2026, 7, 24))

    holidays = of_category(rows, "holiday")
    # Every year a library can hold: the 2026 one and the 29 before, two days either side.
    assert _ranges(holidays) == ["1997-07-19 to 2026-07-23"]
    assert holidays[0]["reason"] == (
        "National Day: the day stands out in 3 years (2023, 2024, 2025), "
        "30 pictures on it across 3 years"
    )


@pytest.mark.feature("detector.holiday")
def test_a_holiday_two_days_ago_is_not_proposed_yet(
    tmp_path: Path, immich_geodata: LocalHttp
) -> None:
    config = write_config(tmp_path, immich_url=immich_geodata.url, home_base=True)

    rows = suggestions(config, _national_days(), date(2026, 7, 23))

    assert of_category(rows, "holiday") == []


@pytest.mark.feature("detector.holiday")
def test_a_day_from_extra_holidays_is_proposed_without_a_home_base(tmp_path: Path) -> None:
    config = write_config(tmp_path, automation={"extra_holidays": ["12-06: Saint Nicholas"]})
    library = (
        Library().on(date(2025, 12, 6), 12).on(date(2024, 12, 6), 12).on(date(2023, 12, 6), 12)
    )

    rows = suggestions(config, library, date(2026, 12, 9))

    holidays = of_category(rows, "holiday")
    assert _ranges(holidays) == ["1997-12-04 to 2026-12-08"]
    assert holidays[0]["reason"] == (
        "Saint Nicholas: the day stands out in 3 years (2023, 2024, 2025), "
        "36 pictures on it across 3 years"
    )


# ── album ────────────────────────────────────────────────────────────────


@pytest.mark.feature("detector.album")
def test_an_album_of_20_pictures_never_filmed_is_proposed(tmp_path: Path) -> None:
    library = (
        Library()
        .month("2026-02", 30)
        .album("album-lisbon", "Lisbon", 20, date(2025, 5, 1), date(2025, 5, 5))
        .album("album-tiny", "Tiny", 19, date(2025, 6, 1), date(2025, 6, 2))
    )

    rows = suggestions(write_config(tmp_path), library, date(2026, 3, 1))

    albums = of_category(rows, "album")
    assert [row["reason"] for row in albums] == ["New album 'Lisbon', 20 pictures, never filmed"]
    assert albums[0]["date_range"] == "2025-05-01 to 2025-05-05"


@pytest.mark.feature("detector.album")
def test_an_album_spanning_more_than_six_months_is_left_out(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    library = (
        Library()
        .month("2026-02", 30)
        .album("album-recents", "Recents", 5000, date(2019, 1, 1), date(2026, 2, 20))
        .album("album-half", "Half a year", 40, date(2025, 1, 1), date(2025, 6, 30))
    )

    rows = suggestions(config, library, date(2026, 3, 1))
    printed = suggest_text(config, library, date(2026, 3, 1))

    assert [row["reason"] for row in of_category(rows, "album")] == [
        "New album 'Half a year', 40 pictures, never filmed"
    ]
    assert "Left out 1 album(s) that span more than six months" in printed


# ── backfill ─────────────────────────────────────────────────────────────


@pytest.mark.feature("detector.backfill")
def test_the_newest_unfilmed_month_with_20_pictures_is_backfilled(tmp_path: Path) -> None:
    library = (
        Library()
        .month("2026-05", 80)  # the latest completed month: the monthly detector's
        .month("2026-04", 19)
        .month("2026-03", 20)
        .month("2025-01", 25)
    )

    rows = suggestions(write_config(tmp_path), library, date(2026, 6, 10))

    assert _ranges(of_category(rows, "backfill")) == ["2026-03-01 to 2026-03-31"]


@pytest.mark.feature("detector.backfill")
def test_last_year_is_backfilled_and_the_year_before_is_not(tmp_path: Path) -> None:
    library = Library().month("2026-05", 80).month("2025-01", 25).month("2024-12", 300)

    rows = suggestions(write_config(tmp_path), library, date(2026, 6, 10))

    assert _ranges(of_category(rows, "backfill")) == ["2025-01-01 to 2025-01-31"]


@pytest.mark.feature("detector.backfill")
def test_a_month_that_has_its_film_is_not_backfilled(tmp_path: Path) -> None:
    from immich_memories.automation.candidates import make_manual_memory_key

    config = write_config(tmp_path)
    library = Library().month("2026-05", 80).month("2026-03", 40).month("2026-02", 40)
    # What `generate --memory-type monthly_highlights --year 2026 --month 3` records.
    record_film(
        config,
        "monthly_highlights",
        make_manual_memory_key("monthly_highlights", date(2026, 3, 1), date(2026, 3, 31)),
    )

    rows = suggestions(config, library, date(2026, 6, 10))

    assert _ranges(of_category(rows, "backfill")) == ["2026-02-01 to 2026-02-28"]


# ── person month ─────────────────────────────────────────────────────────


def _close_kid(pictures: int, days: int) -> tuple[Library, dict]:
    library = Library().person("p-kid", "Kid").person("p-pal", "Pal")
    library.across(date(2026, 5, 2), days, pictures, ("p-kid",))
    library.across(date(2026, 5, 2), 10, 60, ("p-pal",))
    return library, {"p-kid": ("Kid", "inner"), "p-pal": ("Pal", "episodic")}


@pytest.mark.feature("detector.person-month")
def test_a_close_persons_last_month_with_15_pictures_on_4_days_is_proposed(
    tmp_path: Path,
) -> None:
    config = write_config(tmp_path)
    library, registry = _close_kid(pictures=15, days=4)
    import_people(config, registry)

    rows = suggestions(config, library, date(2026, 6, 10))

    months = of_category(rows, "person_monthly")
    # Pal is pictured more but is not close: no month film of Pal.
    assert [(row["person_names"], row["date_range"]) for row in months] == [
        (["Kid"], "2026-05-01 to 2026-05-31")
    ]


@pytest.mark.feature("detector.person-month")
@pytest.mark.parametrize(("pictures", "days"), [(14, 4), (15, 3)], ids=["14-pictures", "3-days"])
def test_a_close_persons_thin_month_says_why_instead(
    tmp_path: Path, pictures: int, days: int
) -> None:
    config = write_config(tmp_path)
    library, registry = _close_kid(pictures=pictures, days=days)
    import_people(config, registry)

    rows = suggestions(config, library, date(2026, 6, 10))
    printed = suggest_text(config, library, date(2026, 6, 10))

    assert of_category(rows, "person_monthly") == []
    assert "No May film for Kid: under 15 pictures over 4 days" in printed
