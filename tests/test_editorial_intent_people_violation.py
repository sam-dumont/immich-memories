"""The intent report's fail-safe for a people condition (#1954).

A people condition is decided strictly per picture at the fetch, so a carrier failing it
should never reach here. If some other path ever did select outside the pool, the
violation must be visible in the intent report rather than shipping silently.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from immich_memories.analysis.editorial_intent import build_editorial_intent
from immich_memories.analysis.editorial_intent_validation import CarrierView, validate_intent
from immich_memories.api.person_expression import PersonExpression
from immich_memories.timeperiod import DateRange

DAY = date(2031, 4, 4)


def _day(day: date) -> DateRange:
    return DateRange(
        datetime(day.year, day.month, day.day, tzinfo=UTC),
        datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=UTC),
    )


def _intent():
    return build_editorial_intent("person_spotlight", [_day(DAY)], brief="Ada", people=["Ada"])


def test_a_carrier_without_the_named_person_on_its_own_picture_is_a_structural_violation():
    report = validate_intent(
        _intent(),
        carriers=[CarrierView("a", DAY, "track", 4.0, people=frozenset())],
        evidence_partitions=set(),
        requested_seconds=30,
        people_condition=PersonExpression("person", value="Ada"),
    )

    assert report.status == "structural_violation"
    assert any(v.code == "people_condition_violated" for v in report.violations)
    assert "a" in report.reason


def test_a_carrier_holding_its_own_named_person_raises_no_violation():
    report = validate_intent(
        _intent(),
        carriers=[CarrierView("a", DAY, "track", 4.0, people=frozenset({"Ada"}))],
        evidence_partitions=set(),
        requested_seconds=30,
        people_condition=PersonExpression("person", value="Ada"),
    )

    assert report.status == "ok"
    assert not report.violations


def test_no_condition_means_no_people_check_at_all():
    report = validate_intent(
        _intent(),
        carriers=[CarrierView("a", DAY, "track", 4.0)],
        evidence_partitions=set(),
        requested_seconds=30,
    )

    assert report.status == "ok"
