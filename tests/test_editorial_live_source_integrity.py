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
    plan = plan_structure(
        bursts(tmp_path, 1),
        StructurePlannerPorts(
            judge=ControlledStoryJudge(),
            thumbnail_hash=lambda _: None,
            clock_offsets=lambda ids: asked.append(tuple(ids)) or [None],
            live_source_integrity=lambda ids: {
                video: {"valid": False, "reason": "decoder-error"} for video in ids
            },
        ),
    ).plan
    assert not asked
    assert all(carrier["kind"] == "live-still" for carrier in plan["carriers"])
    assert sum(len(carrier["members"]) for carrier in plan["carriers"]) == 2
