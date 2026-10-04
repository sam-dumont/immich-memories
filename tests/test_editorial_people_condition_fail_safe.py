"""The structure planner's people-condition fail-safe, through the real seams (#1954, #1969).

The fetch already keeps the pool strict per picture; this checks the SAME function
(`present_on_assets`) and the SAME resolved, face-id condition and `face_accounts`
the fetch used, never the display names on the brief. A resolved id-leaf condition
(what `--person <uuid>`, a people-store alias, or a saved `--group` actually produces)
must never false-positive against the carrier's own `Asset.people`. A genuine mismatch
must be caught and replanned away BEFORE the certified render timing is bound
(`editorial_structure_planner._plan_structure`), not patched into the carriers list
after the fact: a post-hoc rewrite would leave the timing binding pointing at a
membership that no longer exists, and `prepare_certified_timeline` would refuse to
render at all. If nothing is left once every violator is excluded, the run refuses
with a specific reason instead of a generic "no selection".
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from immich_memories.analysis.editorial_rule_reader import NoModelJudge, RuleStructureReader
from immich_memories.analysis.editorial_structure_contract import StructurePlannerPorts
from immich_memories.analysis.editorial_structure_planner import plan_structure
from immich_memories.api.models import Person
from immich_memories.api.person_expression import PersonExpression
from immich_memories.generate import GenerationParams
from immich_memories.processing.editorial_timing import (
    build_editorial_timing_policy,
    prepare_certified_timeline,
)
from tests.conftest import make_clip
from tests.editorial_film_fixtures import film_source, home_days

SPAN = (date(2024, 1, 1), date(2024, 12, 31))
# What the people store resolved the run's one named person to: an opaque id, never a
# display name, and Immich never named the face either (household_fake.py's own shape).
STORE_FACE_ID = "manual:f00dface"
TRANSITION, TRANSITION_DURATION = "crossfade", 0.5


def _film(tmp_path, *, days=4):
    # Starred, so the rules reader has something to pick: this fail-safe is about a
    # carrier the selector DID choose, not about whether it chooses anything at all.
    starred_days = [
        replace(day, starred=True) for day in home_days(date(2024, 3, 2), days, activity="Park day")
    ]
    source = film_source(
        tmp_path,
        starred_days,
        seconds=40,
        span=SPAN,
        product="person_spotlight",
        pictures=2,
    )
    # Engages the certified-timing path (editorial_structure_finishing.py), the same one a
    # real CLI run always has (cli/_editorial_context.py always sets render_timing).
    policy = build_editorial_timing_policy(
        config=source.config,
        target_seconds=source.case.target_seconds,
        memory_type=source.case.product,
        transition=TRANSITION,
        transition_duration=TRANSITION_DURATION,
    )
    return replace(source, render_timing=policy)


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


def _render_params(source, plan, tmp_path):
    """The render-time parameters the CLI would build from a certified plan."""
    clips = [make_clip(asset_id) for asset_id in plan["render_timing"]["source_ids"]]
    return GenerationParams(
        clips=clips,
        output_path=tmp_path / "out.mp4",
        config=source.config,
        target_duration_seconds=source.case.target_seconds,
        memory_type=source.case.product,
        transition=TRANSITION,
        transition_duration=TRANSITION_DURATION,
        editorial_render_timing=plan["render_timing"],
    )


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
    assert "people_condition_dropped" not in plan
    prepare_certified_timeline(_render_params(source, plan, tmp_path))


def test_a_condition_nobody_in_the_pool_holds_refuses_with_a_specific_reason(tmp_path):
    """Owner ruling: better lose a good picture than bundle in a wrong one (#1954)."""
    source = _film(tmp_path)
    for asset in source.assets.values():
        asset.people = []
    source = _with_condition(source, PersonExpression("person", value=STORE_FACE_ID))

    plan = _planned(source)

    assert plan["status"] == "insufficient_material"
    assert plan["intent_report"]["status"] == "insufficient_material"
    assert (
        "no picture satisfies the requested people condition"
        in plan["intent_report"]["reason"].lower()
    )
    assert plan["carriers"] == []


def test_a_flagged_carrier_is_replanned_away_and_the_timing_stays_consistent(tmp_path):
    """Dropping a carrier after its timing is bound would break `prepare_certified_timeline`
    (the certified render membership check); the fix replans before binding instead."""
    source = _film(tmp_path, days=2)
    # The rules reader always prefers a moment's first picture (`-p0`); tagging it with
    # someone else (not nobody: an empty face list is itself a lower-worth signal to the
    # reader) forces the first pass to select it, while its `-p1` sibling -- a real,
    # matching alternative -- is still there for the replan to fall back to.
    bad_id = "d001-m0-p0"
    for asset_id, asset in source.assets.items():
        asset.people = (
            [Person(id="someone-else", name="Someone Else")]
            if asset_id == bad_id
            else [Person(id=STORE_FACE_ID, name="")]
        )
    source = _with_condition(source, PersonExpression("person", value=STORE_FACE_ID))

    plan = _planned(source)

    assert plan.get("people_condition_dropped") == [bad_id]
    carried_ids = {row["asset_id"] for row in plan["carriers"]}
    assert bad_id not in carried_ids
    assert carried_ids == {"d000-m0-p0", "d001-m0-p1"}
    # The certified timing binds the exact same membership the carriers list holds.
    assert plan["render_timing"]["source_ids"] == [row["asset_id"] for row in plan["carriers"]]
    # The real render-time gate: a stale binding would raise here (#1969).
    params = _render_params(source, plan, tmp_path)
    prepare_certified_timeline(params)
    assert [clip.asset.id for clip in params.clips] == [row["asset_id"] for row in plan["carriers"]]


def test_a_carrier_missing_from_captured_evidence_fails_loud_not_silent(tmp_path):
    """The invariant `_contract_check` enforces, through the public `build_result` seam."""
    from datetime import datetime

    from immich_memories.analysis.editorial_structure_record import (
        PlanFacts,
        PlanOutcome,
        build_result,
    )

    source = _film(tmp_path, days=1)
    source = _with_condition(source, PersonExpression("person", value=STORE_FACE_ID))
    ports = StructurePlannerPorts(judge=NoModelJudge(), thumbnail_hash=lambda _asset: None)
    outcome = PlanOutcome(
        contract="contract",
        carriers=[
            {
                "asset_id": "not-a-real-asset",
                "taken": datetime.now().isoformat(),
                "event": "e",
                "seconds": 1.0,
            }
        ],
        cut_carriers=[],
        selection=None,
        chapters=[],
        beats=[],
        threads={},
        tier={},
        worth_reason={},
        share_log={},
        final_duplicates={},
        motion_metrics={},
        selection_stages={},
        evidence_partitions=set(),
        calls=[],
        ladder_reads=0,
        carriers_at_selection=1,
    )
    facts = PlanFacts(
        label=source.case.label,
        target_seconds=source.case.target_seconds,
        contract_key="k",
        wall_sha256="s",
        slots_total=1,
        cap=1,
        source_assets=len(source.assets),
        fam_ids=[],
        anchor_label={},
        period_people={},
        merge_log={},
        document_sources={},
        document_excluded={},
        ineligible={},
        prior=None,
        prior_assets=set(),
        prior_plan_ref=None,
    )

    with pytest.raises(ValueError, match="absent from captured source evidence"):
        build_result(source, ports, facts, outcome)
