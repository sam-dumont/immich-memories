"""On this day goes short only when the years run out of distinct shots (#2134).

A ten-year window around one date holds a few busy recent years and many ordinary ones. Weighed
against the busy years the ordinary ones read as background, and the draft used to fund the busy
years alone: a 45 s film shipped a handful of shots from two or three years.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from immich_memories.analysis.editorial_intent import build_editorial_intent
from immich_memories.timeperiod import DateRange
from tests.editorial_film_fixtures import Day, film_source
from tests.test_editorial_depth_fill import _run


def _years_of_this_day(tmp_path, years, *, busy=()):
    """Three photographed days around 5 October in each year; a busy year is starred and fuller."""
    days = [
        Day(
            date(year, 10, day),
            "Home day",
            moments=4 if year in busy else 1,
            starred=year in busy and day == 5,
        )
        for year in years
        for day in (4, 5, 6)
    ]
    source = film_source(
        tmp_path,
        days,
        seconds=45,
        span=(date(years[0], 10, 4), date(years[-1], 10, 6)),
        product="on_this_day",
        pictures=3,
        picture_gap=timedelta(minutes=12),
    )
    ranges = tuple(
        DateRange(datetime(y, 10, 4, tzinfo=UTC), datetime(y, 10, 6, 23, 59, tzinfo=UTC))
        for y in years
    )
    case = replace(source.case, ranges=ranges)
    return replace(
        source, case=case, intent=build_editorial_intent("on_this_day", ranges, brief=case.brief)
    )


def _years(plan):
    return {carrier["taken"][:4] for carrier in plan["carriers"]}


def test_every_year_that_holds_pictures_gets_a_shot(tmp_path):
    years = tuple(range(2017, 2026))
    plan = _run(_years_of_this_day(tmp_path, years, busy=(2024, 2025)))

    assert _years(plan) == {str(year) for year in years}


def test_a_few_quiet_years_still_fill_the_film_from_their_own_days(tmp_path):
    plan = _run(_years_of_this_day(tmp_path, (2023, 2024, 2025)))

    content = sum(carrier["seconds"] for carrier in plan["carriers"])
    assert _years(plan) == {"2023", "2024", "2025"}
    assert content >= plan["content_cap_seconds"] - 4.5


def _soft_year(source, year):
    """Every picture of one year carries the blur warning, as a year shot all out of focus."""
    for asset_id, asset in source.assets.items():
        if asset.file_created_at.year == year:
            source.annotations[asset_id] += " | SOFT (blurry)"
    return source


def test_a_year_of_only_blurry_pictures_still_gets_its_shot(tmp_path):
    # A lone blurry frame leaves its moment unfunded, but a year the film promised a voice has
    # nothing else to show: leaving it out also left one year of two, and the film was refused.
    plan = _run(_soft_year(_years_of_this_day(tmp_path, (2008, 2025)), 2008))

    assert plan["status"] != "insufficient_material"
    assert _years(plan) == {"2008", "2025"}
