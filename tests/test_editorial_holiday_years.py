"""A holiday film gives every year that kept the day its turn, and no year takes the film.

The automatic Assumption film read twelve years with pictures on the day. One starred
afternoon of one year took half of its 60 s and five of the twelve years got nothing.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from immich_memories.analysis.film.intent import build_editorial_intent
from immich_memories.timeperiod import DateRange
from tests.editorial_film_fixtures import Day, film_source
from tests.test_editorial_depth_fill import _as_videos, _run

# Pictures on 15 August itself, per year, in the shape of the library that made the film.
ON_THE_DAY = {
    2007: 5,
    2015: 33,
    2016: 13,
    2019: 11,
    2020: 11,
    2022: 99,
    2023: 9,
    2024: 174,
    2025: 33,
    2026: 71,
}
STARRED = 2024


def _holiday(tmp_path, *, seconds=60):
    days = [
        Day(
            date(year, 8, 15),
            "Holiday afternoon",
            moments=min(8, math.ceil(count / 12)),
            starred=year == STARRED,
        )
        for year, count in ON_THE_DAY.items()
    ]
    years = sorted(ON_THE_DAY)
    source = film_source(
        tmp_path,
        days,
        seconds=seconds,
        span=(date(years[0], 8, 13), date(years[-1], 8, 17)),
        product="holiday",
        pictures=3,
        picture_gap=timedelta(minutes=12),
    )
    ranges = tuple(
        DateRange(datetime(y, 8, 13, tzinfo=UTC), datetime(y, 8, 17, 23, 59, tzinfo=UTC))
        for y in reversed(years)
    )
    case = replace(source.case, ranges=ranges)
    return replace(
        source, case=case, intent=build_editorial_intent("holiday", ranges, brief=case.brief)
    )


def _shots_per_year(plan) -> Counter:
    return Counter(int(carrier["taken"][:4]) for carrier in plan["carriers"])


def test_every_year_that_kept_the_day_gets_a_shot(tmp_path):
    plan = _run(_holiday(tmp_path))

    assert set(_shots_per_year(plan)) == set(ON_THE_DAY)


def test_one_starred_year_does_not_take_the_film(tmp_path):
    plan = _run(_holiday(tmp_path))

    shots = _shots_per_year(plan)
    fair = math.ceil(sum(shots.values()) / len(ON_THE_DAY))
    assert shots[STARRED] <= fair + 1


def test_a_year_of_long_videos_does_not_take_the_film_either(tmp_path):
    plan = _run(_as_videos(_holiday(tmp_path), seconds=12.0))

    seconds: Counter = Counter()
    for carrier in plan["carriers"]:
        seconds[int(carrier["taken"][:4])] += float(carrier["seconds"])
    total = sum(seconds.values())
    assert set(seconds) == set(ON_THE_DAY)
    assert seconds[STARRED] <= 2 * total / len(ON_THE_DAY)
