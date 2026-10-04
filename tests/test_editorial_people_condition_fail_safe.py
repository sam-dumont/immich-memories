"""The people condition applies to the whole pool once, before any plan is made (#1954, #1969).

The fetch already keeps the pool strict per picture, so this should never exclude
anything -- a defect elsewhere that let a non-matching picture into the pool is the only
way it fires. The fix narrows the selectable pool BEFORE the first (and only) planning
pass: a violator the pass would otherwise have preferred is simply never offered, an
all-violator moment contributes nothing while clean moments still make a film, and
budgets, moment counts and the certified render timing all come out of that one pass
already consistent. A post-hoc rewrite after the plan and its timing are fixed
(editorial_structure_record._contract_check's own people check) is a pure assertion now:
every candidate it sees already satisfies the condition, and it should never find anything.
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
    # Starred, so the rules reader has something to pick: this fail-safe is about which
    # carrier it may choose from, not about whether it chooses anything at all.
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
    assert "people_condition_excluded" not in plan
    prepare_certified_timeline(_render_params(source, plan, tmp_path))


def test_a_clean_pool_plans_identically_whether_or_not_a_condition_is_checked(tmp_path):
    """No condition at all costs nothing extra and changes nothing (#1969)."""
    source = _film(tmp_path)
    for asset in source.assets.values():
        asset.people = [Person(id=STORE_FACE_ID, name="")]
    with_condition = _planned(
        _with_condition(source, PersonExpression("person", value=STORE_FACE_ID))
    )
    without_condition = _planned(_with_condition(source, None))

    assert with_condition["carriers"] == without_condition["carriers"]
    assert (
        with_condition["planning_scope"]["source_assets"]
        == (without_condition["planning_scope"]["source_assets"])
    )
    assert "people_condition_excluded" not in with_condition
    assert "people_condition_excluded" not in without_condition


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
    assert len(plan["people_condition_excluded"]) == len(source.assets)


def test_a_violator_the_pass_would_otherwise_prefer_is_never_offered(tmp_path):
    """The rules reader prefers a moment's first picture; excluding it before planning
    means the pass picks its matching sibling instead, never the violator (#1969)."""
    source = _film(tmp_path, days=2)
    bad_id = "d001-m0-p0"
    for asset_id, asset in source.assets.items():
        asset.people = (
            [Person(id="someone-else", name="Someone Else")]
            if asset_id == bad_id
            else [Person(id=STORE_FACE_ID, name="")]
        )
    source = _with_condition(source, PersonExpression("person", value=STORE_FACE_ID))

    plan = _planned(source)

    assert plan["people_condition_excluded"] == [bad_id]
    carried_ids = {row["asset_id"] for row in plan["carriers"]}
    assert bad_id not in carried_ids
    assert carried_ids == {"d000-m0-p0", "d001-m0-p1"}
    assert not any(
        v["code"] == "people_condition_violated" for v in plan["intent_report"]["violations"]
    )
    # The certified timing binds the exact same membership the carriers list holds --
    # there was only ever one pass, so there is nothing for it to disagree with.
    assert plan["render_timing"]["source_ids"] == [row["asset_id"] for row in plan["carriers"]]
    params = _render_params(source, plan, tmp_path)
    prepare_certified_timeline(params)
    assert [clip.asset.id for clip in params.clips] == [row["asset_id"] for row in plan["carriers"]]


def test_an_all_violator_moment_is_dropped_while_a_clean_moment_still_makes_a_film(tmp_path):
    source = _film(tmp_path, days=2)
    # Day 1 (both its pictures) never shows the requested person at all; day 0 always does.
    for asset_id, asset in source.assets.items():
        asset.people = (
            [Person(id="someone-else", name="Someone Else")]
            if asset_id.startswith("d001-")
            else [Person(id=STORE_FACE_ID, name="")]
        )
    source = _with_condition(source, PersonExpression("person", value=STORE_FACE_ID))

    plan = _planned(source)

    assert set(plan["people_condition_excluded"]) == {"d001-m0-p0", "d001-m0-p1"}
    carried_ids = {row["asset_id"] for row in plan["carriers"]}
    assert carried_ids and carried_ids.issubset({"d000-m0-p0", "d000-m0-p1"})
    assert plan["status"] != "insufficient_material"


def test_the_draft_and_refine_pass_both_see_the_narrowed_pool(tmp_path):
    """The two-pass nas-draft/refine route must never hand refine a violator (#1969)."""
    from tests.test_editorial_duration_planner_integration import source as duration_source

    captured = duration_source(tmp_path, seconds=60, pictures=4)
    asset_ids = sorted(captured.assets)
    bad_id = asset_ids[0]
    for asset_id, asset in captured.assets.items():
        asset.people = (
            [Person(id="someone-else", name="Someone Else")]
            if asset_id == bad_id
            else [Person(id=STORE_FACE_ID, name="")]
        )
        asset.is_favorite = True
    captured = replace(
        captured,
        case=replace(
            captured.case, resolved_person_condition=PersonExpression("person", value=STORE_FACE_ID)
        ),
    )
    ports = StructurePlannerPorts(
        judge=NoModelJudge(), rules=RuleStructureReader(captured), thumbnail_hash=lambda _: None
    )

    def refine(current, draft):
        selected = {c["asset_id"] for c in draft.carriers}
        assert bad_id not in selected
        return current, replace(ports, rules=RuleStructureReader(current), draft=draft)

    result = plan_structure(captured, replace(ports, refine=refine))

    assert bad_id not in {c["asset_id"] for c in result.plan["carriers"]}
    assert result.plan["people_condition_excluded"] == [bad_id]


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
