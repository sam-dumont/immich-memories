"""A free-text request's exclusions reach the brief as hard rules, and the intent report
counts a planted violation of one (#2061)."""

from __future__ import annotations

from datetime import date, datetime

from immich_memories.analysis.editorial_intent import build_editorial_intent
from immich_memories.analysis.editorial_intent_validation import CarrierView, validate_intent
from immich_memories.timeperiod import DateRange

_WINDOW = (DateRange(datetime(2024, 3, 10), datetime(2024, 5, 20, 23, 59, 59)),)
DAY = date(2024, 4, 1)


def _intent(excluded=()):
    return build_editorial_intent(
        "custom", _WINDOW, brief='Make a video about "a trip"', excluded=excluded
    )


def test_exclusions_are_a_hard_rule_in_the_brief():
    intent = _intent(["humans", "children"])

    assert intent.excluded == ("humans", "children")
    block = intent.prompt_block()
    assert "must not show: humans; children" in block
    # Stated once, under its own heading -- not repeated inside "must cover:" too (round 3).
    assert block.count("humans; children") == 1


def test_no_exclusions_leaves_the_brief_unchanged():
    plain = _intent()
    assert plain.excluded == ()
    assert "must not show" not in plain.prompt_block()


def test_excluding_people_drops_the_contradicting_selection_priority():
    # #2061 round 3: a priority still asking for "people... visible" would contradict the
    # hard rule that excludes them.
    with_people = _intent()
    without_people = _intent(["people"])

    assert any("people" in p.lower() for p in with_people.selection_priorities)
    assert not any("people" in p.lower() for p in without_people.selection_priorities)


def test_a_planted_violation_of_an_exclusion_is_counted_in_the_report():
    intent = _intent(["humans"])
    carriers = [
        CarrierView("clean", DAY, "track", 4.0, caption="A mountain under a clear sky"),
        CarrierView("planted", DAY, "track", 4.0, caption="A group of humans on a trail"),
    ]

    report = validate_intent(
        intent, carriers=carriers, evidence_partitions=set(), requested_seconds=30
    )

    assert report.status == "structural_violation"
    violation = next(v for v in report.violations if v.code == "excluded_subject_shown")
    assert violation.asset_id == "planted"
    assert "planted" in report.reason


def test_a_carrier_without_the_excluded_word_raises_no_violation():
    intent = _intent(["humans"])
    carriers = [CarrierView("clean", DAY, "track", 4.0, caption="A mountain under a clear sky")]

    report = validate_intent(
        intent, carriers=carriers, evidence_partitions=set(), requested_seconds=30
    )

    assert report.status == "ok"
    assert not report.violations


def test_a_bare_people_kind_hard_rule_catches_a_man_not_only_the_literal_word():
    # #2061: `pool.py`'s own bare-kind hard rule (`_company_exclusions`) is read by the same
    # curated person-noun matcher the pool itself filters by, not a literal word match. Bare,
    # with no "no" of its own, so "must not show: people" never reads as a double negative.
    intent = _intent(["people"])
    carriers = [CarrierView("planted", DAY, "track", 4.0, caption="A man walking on a trail")]

    report = validate_intent(
        intent, carriers=carriers, evidence_partitions=set(), requested_seconds=30
    )

    assert report.status == "structural_violation"
    assert any(v.code == "excluded_subject_shown" for v in report.violations)
