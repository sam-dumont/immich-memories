"""The intent report's fail-safe for a people condition (#1954).

A people condition is decided strictly per picture at the fetch, so a carrier failing it
should never reach here. The caller (editorial_structure_record.py) is the one that
checks each carrier against the resolved face-id condition with `present_on_assets`,
the exact same function and rule as the fetch; this module only turns the caller's
already-computed violating ids into a visible, named violation.
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


def _intent():
    return build_editorial_intent("person_spotlight", [_day(DAY)], brief="Ada", people=["Ada"])


def test_a_carrier_the_caller_flagged_is_a_named_structural_violation():
    report = validate_intent(
        _intent(),
        carriers=[CarrierView("a", DAY, "track", 4.0)],
        evidence_partitions=set(),
        requested_seconds=30,
        people_violations={"a"},
    )

    assert report.status == "structural_violation"
    violation = next(v for v in report.violations if v.code == "people_condition_violated")
    assert violation.asset_id == "a"
    assert "a" in report.reason


def test_a_carrier_the_caller_did_not_flag_raises_no_violation():
    report = validate_intent(
        _intent(),
        carriers=[CarrierView("a", DAY, "track", 4.0)],
        evidence_partitions=set(),
        requested_seconds=30,
        people_violations=set(),
    )

    assert report.status == "ok"
    assert not report.violations


def test_no_flagged_ids_means_no_people_check_at_all():
    report = validate_intent(
        _intent(),
        carriers=[CarrierView("a", DAY, "track", 4.0)],
        evidence_partitions=set(),
        requested_seconds=30,
    )

    assert report.status == "ok"
