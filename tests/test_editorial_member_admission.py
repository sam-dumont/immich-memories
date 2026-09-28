"""Source refusals apply to an entire carrier before its standing is considered."""

import hashlib
import json

import numpy as np
import pytest

from immich_memories.analysis.editorial_picture_admission import GateRefusal, PictureAdmission
from immich_memories.analysis.editorial_shareability import partition_units
from immich_memories.analysis.editorial_story_standing import StandingGate
from tests.test_editorial_thin_gates import shot


@pytest.mark.parametrize("member", ["burst", "companion", "clip"])
@pytest.mark.parametrize("route", ["draft", "candidate", "recovery"])
def test_all_admission_routes_refuse_excluded_members_before_standing(member, route):
    burst = dict(shot("burst"), members=["burst", "companion"], video_ids=["clip"])
    other = shot("other")
    excluded = {member: "screen-description"}
    eligible, _ = partition_units([burst, other], set(excluded))
    standing = StandingGate(
        lambda _asset: 2,
        line_of=lambda _asset: "People at a gathering",
        life=lambda _asset: True,
        unit_by_asset={row["asset_id"]: ("family", row) for row in eligible},
        pictures_of={"S001": 3},
    )
    admission = PictureAdmission(standing, None, None, excluded=excluded)

    expected = GateRefusal("burst", "S001", "source", "screen-description", "m-burst")
    if route == "draft":
        kept, refused = admission.admit([burst, other], tier_of={"S001": "remarkable"})
        assert kept == [other]
        assert refused == [expected]
    else:
        assert (
            admission.admits(
                burst, cut=[other], tier_of={"S001": "remarkable"}, recovering=route == "recovery"
            )
            == expected
        )
    assert "burst" not in standing.scores


def test_late_preparation_records_a_source_refusal_and_refills_with_the_next_candidate(tmp_path):
    from immich_memories.analysis.editorial_structure_contract import StructurePlannerPorts
    from immich_memories.analysis.editorial_structure_planner import plan_structure
    from tests.editorial_story_fixtures import ControlledStoryJudge
    from tests.test_editorial_duration_planner_integration import source

    captured = source(tmp_path, seconds=60, pictures=20)
    inspected = set()

    # WHY: the preparation boundary supplies new classifier evidence; the real
    # planner, source rules, standing, audience and refill choose the finished cut.
    def prepare(rows):
        fresh = {row["asset_id"] for row in rows} - inspected
        inspected.update(fresh)
        if "picture-015" in fresh:
            captured.annotations["picture-015"] += " | screen=yes"
        return bool(fresh)

    prints = {f"picture-{n:03}": np.eye(20)[0 if n == 1 else n] for n in range(20)}
    plan = plan_structure(
        captured,
        StructurePlannerPorts(
            judge=ControlledStoryJudge(),
            thumbnail_hash=lambda a: hashlib.sha256(a.encode()).hexdigest()[:16],
            scene_print=prints.get,
            prepare_candidates=prepare,
        ),
    ).plan

    kept = {row["asset_id"] for row in plan["carriers"]}
    assert "picture-015" not in kept
    assert "picture-016" in kept
    assert len(kept) == 15
    assert not inspected & {"picture-017", "picture-018", "picture-019"}
    audit = json.loads(
        (captured.artifact_dir / "derived-decisions/picture-admission.private.json").read_text()
    )
    assert {"rule": "source", "detail": "screen-head"}.items() <= next(
        row for row in audit["checks"] if row["asset_id"] == "picture-015"
    ).items()


@pytest.mark.parametrize("member", ["companion", "clip"])
def test_audience_refuses_a_member_without_holding_the_unexcluded_lead(tmp_path, member):
    from immich_memories.analysis.editorial_rule_reader import NoModelJudge
    from immich_memories.analysis.editorial_shareability_tiers import audience_check_for
    from immich_memories.analysis.editorial_structure_audience import AudienceBank, AudienceGate
    from tests.test_editorial_shareability_tiers import Annotation

    lines = {"burst": "People at a gathering.", member: "A screenshot of a dashboard."}
    library = AudienceBank(tmp_path / "audience.json", answerer="rules")
    gate = AudienceGate(
        NoModelJudge(),
        audience="family",
        annotations={"burst": Annotation(lines["burst"])},
        flag_rows={},
        lines=lines,
        bank_path=tmp_path / "shareability.json",
        library=library,
        check_audience=audience_check_for("no_captions"),
    )
    burst = dict(shot("burst"), members=["burst", "companion"], video_ids=["clip"])

    lead_verdict = gate.verdict_of(shot("burst"))
    assert gate.verdict_of(burst) == "do_not_show"
    assert gate.verdicts["burst"]["finding"] == "screen-description"
    assert library.held(member)["finding"] == "screen-description"
    assert library.held("burst") is None
    assert gate.verdict_of(shot("burst")) == lead_verdict
