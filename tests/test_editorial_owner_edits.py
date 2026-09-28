"""Explicit review changes retain selected material and pass ordinary render guards."""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from immich_memories.analysis.editorial_planner import EditorialSelection
from immich_memories.api.models import AssetType
from immich_memories.config_loader import Config
from immich_memories.db import open_store
from immich_memories.generate import GenerationParams
from immich_memories.generate_clips import _validated_render_directives
from immich_memories.processing.editorial_live_render import validate_editorial_live_clip
from immich_memories.processing.editorial_owner_edits import project_editorial_owner_edits
from immich_memories.processing.editorial_timing import (
    bind_editorial_timeline,
    prepare_certified_timeline,
    timing_policy_for_params,
)
from immich_memories.processing.live_material import LiveRenderMaterial, LiveSourceEntry
from tests.conftest import make_clip


@pytest.fixture(autouse=True)
def no_external_work(monkeypatch):
    # The store the review edits are banked in is opened first: opening it checks, once, that
    # its file is not on a network mount, which is local bookkeeping and not a service.
    open_store()

    def forbidden(*_args, **_kwargs):
        pytest.fail("owner review projection must not call models, media tools or services")

    monkeypatch.setattr("socket.socket.connect", forbidden)
    monkeypatch.setattr("subprocess.run", forbidden)
    monkeypatch.setattr("subprocess.Popen", forbidden)
    monkeypatch.setattr("platform.platform", lambda: "macOS-15.0-arm64")


def original_params(tmp_path, *, product="custom"):
    clips = [
        make_clip(f"chosen-{i}", duration=12, file_created_at=datetime(2020 + i, 1, 1, tzinfo=UTC))
        for i in range(4)
    ]
    clips[0].asset.type = AssetType.IMAGE
    live = clips[2]
    live.asset.type = AssetType.IMAGE
    live.asset.live_photo_video_id = "live-companion"
    material = LiveRenderMaterial((LiveSourceEntry(live.asset.id, "live-companion", 0, 0, 12),))
    live.live_burst_still_ids = list(material.still_ids)
    live.live_burst_video_ids = list(material.video_ids)
    live.live_burst_trim_points = list(material.trim_points)
    live.live_burst_shutter_timestamps = list(material.shutter_timestamps)
    live.live_burst_material = material.as_dict()
    live.editorial_live_manifest = {
        "version": "editorial-live-render-v1",
        "material": material.as_dict(),
        "selected_interval": [0, 4],
    }
    config = Config()
    params = GenerationParams(
        clips=clips,
        output_path=tmp_path / "memory.mp4",
        config=config,
        target_duration_seconds=120 if product == "on_this_day" else 60,
        memory_type=product,
        transition=config.defaults.transition,
        transition_duration=config.defaults.transition_duration,
        clip_segments={clip.asset.id: (0, 4) for clip in clips},
        editorial_selections=tuple(
            EditorialSelection(clip.asset.id, 0, 4, mode, frame)
            for clip, mode, frame in zip(
                clips, ("still", "motion", "motion", "still"), (None, None, None, 1.5), strict=True
            )
        ),
    )
    policy = timing_policy_for_params(params)
    timeline = policy.resolve(
        [{"asset_id": c.asset.id, "seconds": 4} for c in clips],
        {c.asset.id: c.asset for c in clips},
    )
    params.editorial_render_timing = bind_editorial_timeline(
        policy,
        timeline,
        [c.asset.id for c in clips],
    )
    params.timeline_plan = timeline
    return params


def project(params, *, selected_ids=None, segments=None, policy=None):
    return project_editorial_owner_edits(
        original_clips=params.clips,
        original_selections=params.editorial_selections,
        original_binding=params.editorial_render_timing,
        selected_ids=[c.asset.id for c in params.clips] if selected_ids is None else selected_ids,
        requested_segments=params.clip_segments if segments is None else segments,
        policy=timing_policy_for_params(params) if policy is None else policy,
    )


def rendered_params(original, projection):
    return replace(
        original,
        clips=list(projection.clips),
        editorial_selections=projection.selections,
        clip_segments=projection.segments,
        timeline_plan=projection.timeline,
        editorial_render_timing=projection.binding,
    )


def test_unchanged_review_reuses_exact_binding_without_edit_record(tmp_path):
    params = original_params(tmp_path)
    result = project(params)
    assert result.binding is params.editorial_render_timing
    assert result.record is None
    assert result.selections == params.editorial_selections
    assert all(left is right for left, right in zip(result.clips, params.clips, strict=True))
    prepare_certified_timeline(rendered_params(params, result))


def test_removal_rebinds_survivors_in_story_order_and_recomputes_title_overhead(tmp_path):
    params = original_params(tmp_path, product="on_this_day")
    before = deepcopy(params)
    result = project(params, selected_ids=["chosen-3", "chosen-0"])
    assert [c.asset.id for c in result.clips] == ["chosen-0", "chosen-3"]
    assert result.binding["source_ids"] == ["chosen-0", "chosen-3"]
    assert result.timeline.max_dividers == 1
    assert result.timeline.title_budget < params.timeline_plan.title_budget
    assert result.record["removed_asset_ids"] == ["chosen-1", "chosen-2"]
    assert result.record["interval_edits"] == []
    assert params == before
    updated = rendered_params(params, result)
    prepare_certified_timeline(updated)
    assert list(_validated_render_directives(updated)) == ["chosen-0", "chosen-3"]


@pytest.mark.parametrize("asset_id", ["chosen-1", "chosen-2"])
def test_motion_trim_updates_directive_and_recertifies_same_live_material(tmp_path, asset_id):
    params = original_params(tmp_path)
    before = deepcopy(params)
    result = project(params, segments={**params.clip_segments, asset_id: (1.0, 3.0)})
    updated = rendered_params(params, result)
    prepare_certified_timeline(updated)
    directive = _validated_render_directives(updated)[asset_id]
    assert (directive.start_time, directive.end_time) == (1, 3)
    assert updated.clip_segments[asset_id] == (1, 3)
    if asset_id == "chosen-2":
        live = next(c for c in updated.clips if c.asset.id == asset_id)
        assert validate_editorial_live_clip(live).as_dict() == params.clips[2].live_burst_material
        assert live.editorial_live_manifest["selected_interval"] == [1, 3]
        assert live.editorial_live_manifest is not params.clips[2].editorial_live_manifest
    assert params == before


@pytest.mark.parametrize("asset_id", ["chosen-0", "chosen-3"])
def test_still_range_changes_hold_without_changing_selected_picture(tmp_path, asset_id):
    params = original_params(tmp_path)
    result = project(params, segments={**params.clip_segments, asset_id: (2, 7)})
    updated = rendered_params(params, result)
    directive = _validated_render_directives(updated)[asset_id]
    assert updated.clip_segments[asset_id] == (0, 5)
    assert (directive.start_time, directive.end_time) == (0, 5)
    assert directive.render_frame_seconds == (1.5 if asset_id == "chosen-3" else None)
    assert result.record["interval_edits"][0]["render_mode"] == "still"


@pytest.mark.parametrize("change", ["transition", "titles"])
def test_explicit_render_settings_rebind_same_selected_material(tmp_path, change):
    params = original_params(tmp_path)
    requested = deepcopy(params)
    if change == "transition":
        requested.transition = "cut"
    else:
        requested.config.title_screens.enabled = False
    result = project(params, policy=timing_policy_for_params(requested))
    assert result.record["timing_policy_changed"] is True
    assert result.record["interval_edits"] == []
    assert result.record["removed_asset_ids"] == []
    assert result.clips == tuple(params.clips)
    assert result.selections == params.editorial_selections
    prepare_certified_timeline(rendered_params(requested, result))


@pytest.mark.parametrize(
    "interval",
    [
        (0, 0),
        (4, 2),
        (-1, 3),
        (0, 13),
        (0, float("nan")),
        (0, float("inf")),
        (True, 2),
        None,
        (0,),
        (0, 1, 2),
        (None, 2),
    ],
)
def test_invalid_motion_trim_fails_before_media(tmp_path, interval):
    params = original_params(tmp_path)
    with pytest.raises(ValueError, match="Review trim"):
        project(params, segments={**params.clip_segments, "chosen-2": interval})


@pytest.mark.parametrize("ids", [[], ["added"], ["chosen-0", "chosen-0"]])
def test_empty_added_or_duplicated_material_is_rejected(tmp_path, ids):
    with pytest.raises(ValueError, match="Keep at least|outside the chosen memory"):
        project(original_params(tmp_path), selected_ids=ids)


def test_owner_edit_cannot_bypass_original_binding_or_live_validation(tmp_path):
    params = original_params(tmp_path)
    params.editorial_render_timing["source_ids"].pop()
    with pytest.raises(ValueError, match="binding changed"):
        project(params, selected_ids=["chosen-0"])
    params = original_params(tmp_path)
    params.clips[2].editorial_live_manifest["selected_interval"] = [0, 5]
    with pytest.raises(ValueError, match="Original editorial review interval changed"):
        project(params, segments={"chosen-2": (1, 2)})


def test_a_hold_past_the_titles_budget_makes_the_film_longer_and_shortens_nothing(tmp_path):
    params = original_params(tmp_path)
    before = deepcopy(params)

    longer = project(params, segments={**params.clip_segments, "chosen-0": (0, 60)})

    assert longer.segments["chosen-0"] == (0, 60)
    assert all(longer.segments[key] == (0, 4) for key in ("chosen-1", "chosen-2", "chosen-3"))
    assert longer.timeline.content_budget >= 60 + 3 * 4
    assert longer.binding["policy"]["target_seconds"] > params.target_duration_seconds
    assert params == before


def swap_project(params, sibling, *, siblings=None, selected_ids=None, segments=None):
    return project_editorial_owner_edits(
        original_clips=params.clips,
        original_selections=params.editorial_selections,
        original_binding=params.editorial_render_timing,
        selected_ids=[c.asset.id for c in params.clips] if selected_ids is None else selected_ids,
        requested_segments=params.clip_segments if segments is None else segments,
        policy=timing_policy_for_params(params),
        replacements={"chosen-0": sibling},
        moment_siblings={"chosen-0": ["sibling-0"]} if siblings is None else siblings,
    )


def test_a_recorded_sibling_takes_the_shot_s_place_and_passes_the_render_guards(tmp_path):
    params = original_params(tmp_path)
    before = deepcopy(params)
    sibling = make_clip("sibling-0", duration=12, file_created_at=datetime(2020, 1, 2, tzinfo=UTC))
    sibling.asset.type = AssetType.IMAGE

    result = swap_project(params, sibling)

    assert [c.asset.id for c in result.clips] == ["sibling-0", "chosen-1", "chosen-2", "chosen-3"]
    assert result.binding["source_ids"] == ["sibling-0", "chosen-1", "chosen-2", "chosen-3"]
    assert result.segments["sibling-0"] == (0.0, 4.0)
    assert result.record["replacements"] == [{"original": "chosen-0", "replacement": "sibling-0"}]
    assert params == before
    updated = rendered_params(params, result)
    prepare_certified_timeline(updated)
    directive = _validated_render_directives(updated)["sibling-0"]
    assert directive.render_mode == "still"


@pytest.mark.parametrize(
    ("replacement", "siblings"),
    [("a-stranger", {"chosen-0": ["sibling-0"]}), ("chosen-3", {"chosen-0": ["chosen-3"]})],
)
def test_a_swap_to_anything_but_a_new_recorded_sibling_is_refused(tmp_path, replacement, siblings):
    params = original_params(tmp_path)
    clip = next((c for c in params.clips if c.asset.id == replacement), None) or make_clip(
        replacement, duration=12, file_created_at=datetime(2020, 1, 2, tzinfo=UTC)
    )

    with pytest.raises(ValueError, match="moment"):
        swap_project(params, clip, siblings=siblings)
