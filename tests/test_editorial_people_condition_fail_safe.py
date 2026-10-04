"""The structure planner's people-condition fail-safe, through the real seams (#1954).

The fetch already keeps the pool strict per picture; this checks the SAME function
(`present_on_assets`) and the SAME resolved, face-id condition and `face_accounts`
the fetch used, never the display names on the brief. Two things must both hold:
a resolved id-leaf condition (what `--person <uuid>`, a people-store alias, or a
saved `--group` actually produces) must never false-positive against the carrier's
own `Asset.people`, and a genuine mismatch must be caught, reported, and dropped
before render rather than ignored.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from immich_memories.analysis.editorial_people import adapt_editorial_people
from immich_memories.analysis.editorial_rule_reader import NoModelJudge, RuleStructureReader
from immich_memories.analysis.editorial_runtime import EditorialRunContext
from immich_memories.analysis.editorial_runtime_backend import ProductionPostCardBackend
from immich_memories.analysis.editorial_runtime_ports import EditorialRuntimePorts
from immich_memories.analysis.editorial_structure_contract import (
    StructurePlannerPorts,
    StructurePlanningResult,
)
from immich_memories.analysis.editorial_structure_planner import plan_structure
from immich_memories.analysis.selection_trace import Trace
from immich_memories.api.models import Person
from immich_memories.api.person_expression import PersonExpression
from tests.annotation_rows import annotation_store
from tests.editorial_film_fixtures import film_source, home_days

SPAN = (date(2024, 1, 1), date(2024, 12, 31))
# What the people store resolved the run's one named person to: an opaque id, never a
# display name, and Immich never named the face either (household_fake.py's own shape).
STORE_FACE_ID = "manual:f00dface"


def _film(tmp_path, *, days=4):
    # Starred, so the rules reader has something to pick: this fail-safe is about a
    # carrier the selector DID choose, not about whether it chooses anything at all.
    starred_days = [
        replace(day, starred=True) for day in home_days(date(2024, 3, 2), days, activity="Park day")
    ]
    return film_source(
        tmp_path,
        starred_days,
        seconds=40,
        span=SPAN,
        product="person_spotlight",
        pictures=2,
    )


def _with_condition(source, condition: PersonExpression | None):
    return replace(source, case=replace(source.case, resolved_person_condition=condition))


def _planned(source):
    return plan_structure(
        source,
        StructurePlannerPorts(
            judge=NoModelJudge(),
            thumbnail_hash=lambda _asset: None,
            rules=RuleStructureReader(source),
        ),
    ).plan


def test_a_resolved_id_leaf_condition_has_no_false_positive_on_an_unnamed_face(tmp_path):
    source = _film(tmp_path)
    for asset in source.assets.values():
        asset.people = [Person(id=STORE_FACE_ID, name="")]
    source = _with_condition(source, PersonExpression("person", value=STORE_FACE_ID))

    plan = _planned(source)

    assert plan["intent_report"]["status"] != "structural_violation"
    assert not any(
        v["code"] == "people_condition_violated" for v in plan["intent_report"]["violations"]
    )
    assert plan["carriers"]


def test_a_condition_nobody_in_the_pool_holds_is_caught_and_reported(tmp_path):
    source = _film(tmp_path)
    for asset in source.assets.values():
        asset.people = []
    source = _with_condition(source, PersonExpression("person", value=STORE_FACE_ID))

    plan = _planned(source)

    assert plan["intent_report"]["status"] == "structural_violation"
    violated = [
        v for v in plan["intent_report"]["violations"] if v["code"] == "people_condition_violated"
    ]
    assert violated
    assert {v["asset_id"] for v in violated} == {row["asset_id"] for row in plan["carriers"]}


def _fake_backend(source_input, result):
    case = source_input.case
    return ProductionPostCardBackend(
        config=source_input.config,
        context=EditorialRunContext(
            case.key,
            case.label,
            case.product,
            case.ranges,
            case.target_seconds,
            source_input.artifact_dir,
        ),
        people=adapt_editorial_people({}),
        thumbnail_cache=object(),
        store=annotation_store(),
        bank_root=source_input.bank_dir,
        ports=EditorialRuntimePorts(
            structure_planner=lambda *_: result,
            structure_ports_factory=lambda *_: object(),
        ),
    )


def _rigged_result(source_input, *, good_id, bad_id):
    assets = source_input.assets
    carriers = [
        {"asset_id": a.id, "taken": a.file_created_at.isoformat(), "kind": "still"}
        for a in sorted(assets.values(), key=lambda a: a.file_created_at)
        if a.id in (good_id, bad_id)
    ]
    return StructurePlanningResult(
        {
            "status": "structural_violation",
            "intent_report": {
                "status": "structural_violation",
                "reason": f"{bad_id} was selected but does not satisfy the requested people condition",
                "violations": [
                    {
                        "code": "people_condition_violated",
                        "severity": "structural",
                        "partition": None,
                        "detail": f"{bad_id} was selected but does not satisfy the requested "
                        "people condition on its own recognised faces",
                        "asset_id": bad_id,
                    }
                ],
            },
            "carriers": carriers,
        },
        "contract",
        "diagnostic selection",
        {},
    )


def test_a_flagged_carrier_is_dropped_before_render_with_a_visible_warning(tmp_path):
    """Owner ruling: better lose a good picture than bundle in a wrong one (#1954)."""
    source = _film(tmp_path, days=1)
    good_id, bad_id = sorted(source.assets)[:2]
    result = _rigged_result(source, good_id=good_id, bad_id=bad_id)
    backend = _fake_backend(source, result)
    trace = Trace()

    plan = backend.edit(source, trace=trace)

    selected_ids = {selection.asset_id for selection in plan.selections}
    assert selected_ids == {good_id}
    assert bad_id not in selected_ids
    assert any("dropped before render" in warning for warning in trace.warnings)
    assert bad_id not in {row["asset_id"] for row in result.plan["carriers"]}


def test_a_carrier_missing_from_captured_evidence_fails_loud_not_silent(tmp_path):
    from immich_memories.analysis.editorial_structure_record import _people_condition_violations

    source = _film(tmp_path, days=1)
    condition = PersonExpression("person", value=STORE_FACE_ID)

    with pytest.raises(ValueError, match="absent from captured source evidence"):
        _people_condition_violations(["not-a-real-asset"], source.assets, condition, {})
