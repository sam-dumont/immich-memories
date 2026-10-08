"""Late clip evidence changes how the retained photograph plays."""

from dataclasses import replace
from functools import partial

from immich_memories.analysis.editorial_rule_reader import NoModelJudge, RuleStructureReader
from immich_memories.analysis.editorial_speech import resolve_speech_cuts
from immich_memories.analysis.editorial_structure_contract import StructurePlannerPorts
from immich_memories.analysis.editorial_structure_planner import plan_structure
from tests.conftest import make_asset
from tests.test_editorial_duration_planner_integration import source


def test_fresh_live_frame_quality_changes_playback_but_keeps_the_photo(tmp_path):
    captured = source(tmp_path, seconds=60, pictures=8)
    companions = {}
    for asset in captured.assets.values():
        asset.is_favorite = True
        asset.live_photo_video_id = "clip-" + asset.id
        companions[asset.live_photo_video_id] = make_asset(
            asset.live_photo_video_id, duration=3.003, file_created_at=asset.file_created_at
        )
    captured = replace(
        captured,
        companion_assets=companions,
        motion_residuals={a: {"residual": 9.0} for a in captured.assets},
    )
    ports = StructurePlannerPorts(
        judge=NoModelJudge(),
        rules=RuleStructureReader(captured),
        thumbnail_hash=lambda _: None,
        # WHY: the speech detector is external; keep production's interval binding so
        # the NAS draft has exact endpoints before new frame evidence changes playback.
        resolve_speech=partial(resolve_speech_cuts, regions_for=lambda _: [(2.8, 3.003)], buffer=0),
    )
    baseline = plan_structure(captured, ports)
    assert any(c["kind"] == "live-motion" for c in baseline.plan["carriers"])
    assert all("end_time" in c for c in baseline.plan["carriers"])

    # WHY: frame classification is the external boundary; the real planner must
    # apply its late result to carriers already chosen by the NAS draft.
    def refine(current, draft):
        enriched = replace(current, clip_frames=dict.fromkeys(companions, "subject_often_missing"))
        return enriched, replace(ports, rules=RuleStructureReader(enriched), draft=draft)

    result = plan_structure(captured, replace(ports, refine=refine))
    assert {c["asset_id"] for c in result.plan["carriers"]} == {
        c["asset_id"] for c in baseline.plan["carriers"]
    }
    assert all(c["kind"] == "live-still" for c in result.plan["carriers"])


def test_unchanged_bursts_are_reported_once_across_draft_and_refinement(tmp_path, caplog):
    import logging

    captured = source(tmp_path, seconds=30, pictures=8)
    captured.config.photos.burst_window_seconds = 1200
    ports = StructurePlannerPorts(
        judge=NoModelJudge(),
        rules=RuleStructureReader(captured),
        thumbnail_hash=lambda key: "0000000000000000" if key.endswith(("000", "001")) else None,
    )
    refinements = []

    def refine(current, draft):
        refinements.append(draft)
        return current, replace(ports, draft=draft)

    with caplog.at_level(logging.INFO):
        result = plan_structure(captured, replace(ports, refine=refine))

    assert len(refinements) == 1
    assert result.plan["carriers"]
    messages = [r.getMessage() for r in caplog.records if "Burst de-duplication:" in r.getMessage()]
    assert len(messages) == 1
    assert "1 of 8 photos dropped" in messages[0]
