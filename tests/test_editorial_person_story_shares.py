"""A person's year is not one day of it.

A birthday film of a friend's year planned 28 shots, 9 of them one wedding afternoon (11 with
the night after it): the thin days had nothing more to give, so the depth fill poured every
free second into the one day that had. A holiday film had the same fault across its years
(#2441) and now goes short rather than hand one occurrence the turns the others had no picture
for; a person film does the same across its stories: none deepens past a quarter of the cut,
or half for the one story the plan made dominant.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import date, timedelta

from tests.editorial_film_fixtures import Day, film_source
from tests.test_editorial_depth_fill import _run

WEDDING = date(2025, 9, 13)


def _person_year(tmp_path, product="person_spotlight"):
    others = [
        Day(date(2025, 10, 4) + timedelta(days=24 * n), f"Afternoon {n}", starred=True)
        for n in range(9)
    ]
    return film_source(
        tmp_path,
        [Day(WEDDING, "Wedding", moments=8), *others],
        seconds=245,
        span=(date(2025, 8, 31), date(2026, 8, 30)),
        product=product,
        pictures=3,
        picture_gap=timedelta(minutes=6),
    )


def _per_day(plan) -> Counter:
    return Counter(carrier["taken"][:10] for carrier in plan["carriers"])


def test_one_day_does_not_take_a_person_film(tmp_path):
    plan = _run(_person_year(tmp_path))

    days = _per_day(plan)
    assert days[WEDDING.isoformat()] <= math.ceil(sum(days.values()) / 4), days
    # Every other day keeps its shot: the film goes short, it does not drop the thin days.
    assert len(days) == 10


def test_a_month_still_deepens_its_one_big_day(tmp_path):
    """Only a person film is held to shares: a month keeps filling the day that has more."""
    month = _per_day(_run(_person_year(tmp_path, "custom")))
    person = _per_day(_run(_person_year(tmp_path / "person")))

    assert month[WEDDING.isoformat()] > person[WEDDING.isoformat()]
