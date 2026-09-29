"""A film with real material is made shorter, never refused (#1595).

The owner's ruling: "if there's something, even if small, we try". A special day that kept two
real shots (13.1 s of a 37.5 s target) was refused as insufficient material; the day before, the
same request made a film of four. Only a request that shows nothing is "not possible", and a
recurring film still needs two occurrences to be a recurring film.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from immich_memories.analysis.editorial_intent import build_editorial_intent
from immich_memories.analysis.editorial_intent_validation import CarrierView, validate_intent
from immich_memories.timeperiod import DateRange

DAY = date(2031, 4, 4)


def _day(day: date) -> DateRange:
    return DateRange(
        datetime(day.year, day.month, day.day, tzinfo=UTC),
        datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=UTC),
    )


def _special_day():
    return build_editorial_intent("special_day", [_day(DAY)], brief="Track day")


def test_two_real_shots_make_a_short_film_not_nothing():
    report = validate_intent(
        _special_day(),
        carriers=[CarrierView("a", DAY, "track", 6.5), CarrierView("b", DAY, "track", 6.6)],
        evidence_partitions=set(),
        requested_seconds=37.5,
    )

    assert report.status != "insufficient_material"


def test_one_real_shot_is_still_a_film():
    report = validate_intent(
        _special_day(),
        carriers=[CarrierView("a", DAY, "track", 4.0)],
        evidence_partitions=set(),
        requested_seconds=60,
    )

    assert report.status != "insufficient_material"


def test_a_request_that_shows_nothing_is_not_possible():
    report = validate_intent(
        _special_day(), carriers=[], evidence_partitions=set(), requested_seconds=37.5
    )

    assert report.status == "insufficient_material"


def test_a_recurring_film_still_needs_two_occurrences():
    years = [_day(date(year, 5, 2)) for year in (2030, 2031)]
    intent = build_editorial_intent("on_this_day", years, brief="This day")
    one_year = [CarrierView("a", date(2030, 5, 2), "morning", 4)]
    both = [*one_year, CarrierView("b", date(2031, 5, 2), "morning", 4)]

    def status(carriers):
        return validate_intent(
            intent, carriers=carriers, evidence_partitions=set(), requested_seconds=60
        ).status

    assert status(one_year) == "insufficient_material"
    assert status(both) != "insufficient_material"
