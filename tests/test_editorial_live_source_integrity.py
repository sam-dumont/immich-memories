"""Original-companion integrity refuses motion while retaining the selected photograph."""

from dataclasses import replace

from immich_memories.analysis.editorial_structure_contract import StructurePlannerPorts
from immich_memories.analysis.editorial_structure_planner import plan_structure
from immich_memories.processing.editorial_timing import build_editorial_timing_policy
from tests.editorial_story_fixtures import ControlledStoryJudge
from tests.test_editorial_event_motion_material import live_source


def test_invalid_original_keeps_the_same_selected_still_with_explicit_provenance(tmp_path):
    source = live_source(tmp_path, pictures=1, add_context=False)
    source.config.title_screens.enabled = False
    source = replace(
        source,
        render_timing=build_editorial_timing_policy(
            config=source.config,
            target_seconds=15,
            memory_type=source.case.product,
            transition="cut",
        ),
    )
    still_id = next(iter(source.assets))
    proof = {
        "source_sha256": "a" * 64,
        "video_stream_index": 0,
        "decoder_identity": "synthetic-decoder-version",
        "presentation_policy": "complete-visible-video-presentation-v1",
        "valid": False,
        "reason": "non-increasing decoded presentation timestamps",
    }

    def original_integrity(video_ids):
        # WHY: replace only the original file/decoder boundary; selection remains real.
        return dict.fromkeys(video_ids, proof)

    result = plan_structure(
        source,
        StructurePlannerPorts(
            judge=ControlledStoryJudge(),
            thumbnail_hash=lambda _: None,
            live_source_integrity=original_integrity,
        ),
    ).plan

    assert len(result["carriers"]) == 1
    carrier = result["carriers"][0]
    assert carrier["asset_id"] == still_id
    assert carrier["members"] == [still_id]
    assert carrier["kind"] == "live-still"
    assert carrier["motion_candidate"] is False
    assert carrier["source_integrity"] == {"video-0": proof}
    assert result["render_timing"]["source_ids"] == [still_id]

    from types import SimpleNamespace

    from immich_memories.analysis.editorial_source_route import project_source_rendering
    from immich_memories.generate_clips import _prefetch_assets, _validated_render_directives
    from tests.test_editorial_source_route import demand

    _, candidates = demand(list(source.assets.values()))
    projected = project_source_rendering(
        result["carriers"],
        candidates,
        config=source.config,
        include_live_photos=True,
        companion_assets=source.companion_assets,
    )
    clips = [row.clip for row in projected.candidates if row.clip.asset.id == still_id]
    directives = _validated_render_directives(
        SimpleNamespace(clips=clips, editorial_selections=projected.plan.selections)
    )
    assert directives[still_id].render_mode == "still"
    assert _prefetch_assets(clips, directives) == []


def test_missing_original_proof_cannot_certify_motion(tmp_path):
    import pytest

    source = live_source(tmp_path, pictures=1, add_context=False)
    with pytest.raises(ValueError, match="every declared Live original"):
        plan_structure(
            source,
            StructurePlannerPorts(
                judge=ControlledStoryJudge(),
                thumbnail_hash=lambda _: None,
                live_source_integrity=lambda _: {},
            ),
        )


def test_valid_original_provenance_survives_measured_stitch(tmp_path):
    from tests.test_live_clock_offsets_on_demand import bursts, counting_offsets

    captured = bursts(tmp_path, 1)
    asked = []
    proof = {"valid": True, "source_sha256": "a" * 64}
    plan = plan_structure(
        captured,
        StructurePlannerPorts(
            judge=ControlledStoryJudge(),
            thumbnail_hash=lambda _: None,
            clock_offsets=counting_offsets(asked),
            live_source_integrity=lambda ids: dict.fromkeys(ids, proof),
        ),
    ).plan
    assert asked
    assert all(carrier["source_integrity"] for carrier in plan["carriers"])


def test_invalid_original_is_not_retried_as_an_own_clip(tmp_path):
    from tests.test_live_clock_offsets_on_demand import bursts

    asked = []
    calls_at_admission = []

    def integrity(ids):
        calls_at_admission.append(len(asked))
        return {video: {"valid": False, "reason": "decoder-error"} for video in ids}

    captured = bursts(tmp_path, 1)
    ports = StructurePlannerPorts(
        judge=ControlledStoryJudge(),
        thumbnail_hash=lambda _: None,
        clock_offsets=lambda ids: asked.append(tuple(ids)) or [None],
    )
    baseline = plan_structure(captured, ports).plan
    asked.clear()
    plan = plan_structure(captured, replace(ports, live_source_integrity=integrity)).plan
    assert calls_at_admission == [len(asked)]
    assert all(carrier["kind"] == "live-still" for carrier in plan["carriers"])
    assert [(c["asset_id"], c["members"]) for c in plan["carriers"]] == [
        (c["asset_id"], c["members"]) for c in baseline["carriers"]
    ]


def test_only_final_measured_originals_are_admitted_once(tmp_path):
    from immich_memories.processing.live_material import LiveRenderMaterial
    from tests.test_live_clock_offsets_on_demand import bursts

    asked = []
    captured = bursts(tmp_path, 12)
    result = plan_structure(
        captured,
        StructurePlannerPorts(
            judge=ControlledStoryJudge(),
            thumbnail_hash=lambda _: None,
            # WHY: actual failed join binds the retained photograph to its own clip.
            clock_offsets=lambda ids: [None] * (len(ids) - 1),
            live_source_integrity=lambda ids: (
                asked.append(tuple(ids)) or {video: {"valid": True} for video in ids}
            ),
        ),
    ).plan
    expected = [
        LiveRenderMaterial.from_dict(c["live_material"]).video_ids
        for c in result["carriers"]
        if c["kind"] == "live-motion"
    ]
    assert asked == expected
    assert all(len(ids) == 1 for ids in asked)
    assert all(c["source_integrity"] for c in result["carriers"] if c["kind"] == "live-motion")


def test_preliminary_rules_draft_does_not_read_originals(tmp_path):
    from tests.test_live_clock_offsets_on_demand import bursts, counting_offsets

    refined = False
    asked = []

    def integrity(ids):
        assert refined, "Discarded preliminary draft must not acquire original bytes"
        asked.append(tuple(ids))
        return {video: {"valid": True} for video in ids}

    ports = StructurePlannerPorts(
        judge=ControlledStoryJudge(),
        thumbnail_hash=lambda _: None,
        clock_offsets=counting_offsets([]),
        live_source_integrity=integrity,
    )

    def refine(current, draft):
        nonlocal refined
        refined = True
        return current, replace(ports, draft=draft)

    result = plan_structure(bursts(tmp_path, 2), replace(ports, refine=refine)).plan
    assert asked
    assert all(c.get("source_integrity") for c in result["carriers"] if c["kind"] == "live-motion")


def test_final_still_disposition_fails_if_the_same_pictures_cannot_fit(tmp_path):
    import pytest

    from immich_memories.analysis.editorial_structure_finishing import (
        PlanRun,
        admit_retained_originals,
    )
    from immich_memories.analysis.editorial_structure_material import build_material, read_wall

    source = live_source(tmp_path, pictures=1, add_context=False)
    material = build_material(
        source,
        StructurePlannerPorts(
            judge=ControlledStoryJudge(),
            thumbnail_hash=lambda _: None,
            live_source_integrity=lambda ids: {video: {"valid": False} for video in ids},
        ),
        read_wall(source),
    )
    carriers = [unit for units in material.units.values() for unit in units]
    run = PlanRun(carriers=carriers, final_content_cap=0.5)
    identity = [(c["asset_id"], c["members"]) for c in carriers]
    with pytest.raises(ValueError, match="without removing selected pictures"):
        admit_retained_originals(run, source, material.builder)
    assert [(c["asset_id"], c["members"]) for c in run.carriers] == identity
    assert all(c["kind"] == "live-still" for c in run.carriers)


def test_title_enabled_still_admission_keeps_budget_and_sealed_timing_consistent(tmp_path):
    from immich_memories.processing.editorial_timing import read_editorial_timeline

    source = live_source(tmp_path, pictures=1, add_context=False)
    source.config.title_screens.enabled = True
    source = replace(
        source,
        render_timing=build_editorial_timing_policy(
            config=source.config,
            target_seconds=15,
            memory_type=source.case.product,
            transition="crossfade",
        ),
    )
    ports = StructurePlannerPorts(judge=ControlledStoryJudge(), thumbnail_hash=lambda _: None)
    baseline = plan_structure(source, ports).plan
    result = plan_structure(
        source,
        replace(ports, live_source_integrity=lambda ids: {v: {"valid": False} for v in ids}),
    ).plan
    assert [(c["asset_id"], c["members"]) for c in result["carriers"]] == [
        (c["asset_id"], c["members"]) for c in baseline["carriers"]
    ]
    resolved = source.render_timing.resolve(result["carriers"], source.assets)
    sealed = read_editorial_timeline(result["render_timing"])
    assert sealed.title_budget > 0
    assert sealed == resolved
    assert result["content_cap_seconds"] == min(
        baseline["content_cap_seconds"],
        resolved.content_budget,
    )
    assert sum(c["seconds"] for c in result["carriers"]) <= result["content_cap_seconds"]
    assert result["render_timing"]["source_ids"] == baseline["render_timing"]["source_ids"]


def test_pending_month_dividers_refit_after_final_still_admission(tmp_path):
    from immich_memories.analysis.editorial_structure_finishing import (
        PlanRun,
        admit_retained_originals,
        resolve_motion_and_timing,
    )
    from immich_memories.analysis.editorial_structure_material import build_material, read_wall

    source = live_source(tmp_path, pictures=5, add_context=False)
    source = replace(
        source,
        case=replace(source.case, target_seconds=32, product="year_in_review"),
        intent=replace(source.intent, product="year_in_review"),
    )
    for index, asset in enumerate(source.assets.values()):
        asset.file_created_at = asset.file_created_at.replace(month=index + 1)
        source.companion_assets[asset.live_photo_video_id].duration_seconds = 20.0
    source.config.title_screens.enabled = True
    source = replace(
        source,
        render_timing=build_editorial_timing_policy(
            config=source.config,
            target_seconds=32,
            memory_type=source.case.product,
            transition="cut",
        ),
    )
    ports = StructurePlannerPorts(
        judge=ControlledStoryJudge(),
        thumbnail_hash=lambda _: None,
        live_source_integrity=lambda ids: {v: {"valid": False} for v in ids},
    )
    material = build_material(source, ports, read_wall(source))
    carriers = [unit for units in material.units.values() for unit in units]
    run = PlanRun(carriers=carriers, bind_stitch=material.builder.measured_stitch)
    resolve_motion_and_timing(run, source, ports)
    # #2065: the tight cut still keeps the one month divider that fits rather than dropping to none.
    assert run.render_timeline.divider_policy == "capped"
    assert run.render_timeline.max_dividers == 1
    old_cap = run.final_content_cap
    identities = [(c["asset_id"], c["members"]) for c in run.carriers]
    admit_retained_originals(run, source, material.builder)
    assert run.render_timeline.divider_policy == "all"
    assert run.final_content_cap == min(old_cap, run.render_timeline.content_budget)
    assert sum(c["seconds"] for c in run.carriers) <= run.final_content_cap
    assert [(c["asset_id"], c["members"]) for c in run.carriers] == identities
    assert all(c["kind"] == "live-still" for c in run.carriers)
    assert run.render_timeline == source.render_timing.resolve(run.carriers, source.assets)
