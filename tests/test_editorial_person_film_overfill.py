"""A sparse life is a short film, not one party night shown nine times.

An all-time person film of a friend held one quiet day for most years and one dense night: the
cut came out at 68 shots, nine of them that one night and seven of them a second frame of a
moment the cut already showed. The film was padded to its length from the one place that had
pictures left, instead of going short when the distinct moments ran out.

A person film is about the person across their life: a moment the cut shows gets one shot, a
day the plan weighed as a small one keeps the two shots its weight grants, and when that runs
out the film is shorter.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from tests.editorial_film_fixtures import Day, film_source
from tests.test_editorial_depth_fill import _run

LIFE = (date(2010, 1, 1), date(2025, 12, 31))
PARTY = date(2016, 6, 4)
QUIET_YEARS = [year for year in range(2010, 2026) if year not in (2013, 2014, 2016, 2019)]


def _sparse_life(tmp_path, *, pictures=3, picture_gap=timedelta(minutes=6), starred=True):
    """A quiet day most years (two starred moments, so the plan weighs it), and one party night
    of eight moments. Every moment holds a few pictures, a real five minutes or more apart."""
    quiet = [
        Day(date(year, 3, 10), f"Afternoon in {year}", moments=2, starred=starred)
        for year in QUIET_YEARS
    ]
    return film_source(
        tmp_path,
        sorted([*quiet, Day(PARTY, "Party night", moments=8)], key=lambda day: day.day),
        seconds=600,
        span=LIFE,
        product="person_spotlight",
        pictures=pictures,
        picture_gap=picture_gap,
    )


def _moments(plan) -> Counter:
    return Counter(carrier["moment"] for carrier in plan["carriers"])


def test_a_moment_the_cut_shows_gets_one_shot(tmp_path):
    plan = _run(_sparse_life(tmp_path))

    repeated = {moment: n for moment, n in _moments(plan).items() if n > 1}
    assert not repeated, repeated


def test_a_burst_inside_one_moment_is_one_shot_in_a_person_film(tmp_path):
    """Ten frames half a minute apart are one moment, however many pictures it holds: a day the
    plan reads as a glance does not deepen because its moment is a long burst (#2211 is about a
    special day's big event, not a person's life)."""
    plan = _run(
        _sparse_life(tmp_path, pictures=10, picture_gap=timedelta(seconds=30), starred=False)
    )

    repeated = {moment: n for moment, n in _moments(plan).items() if n > 1}
    assert not repeated, repeated


def test_the_party_night_does_not_pad_the_film(tmp_path):
    plan = _run(_sparse_life(tmp_path))

    days = Counter(carrier["taken"][:10] for carrier in plan["carriers"])
    assert days[PARTY.isoformat()] <= 2, days
    # Every quiet year keeps its shot: the film loses the padding, not the years.
    assert {int(day[:4]) for day in days} >= set(QUIET_YEARS)
    # And the film says it went short rather than filling its length.
    assert plan["duration_realization"]["status"] == "editorial_shortfall"
    assert plan["content_seconds"] < plan["duration_realization"]["content_budget_seconds"] / 2
