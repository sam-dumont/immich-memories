"""A rendered editorial film retains every selected carrier in its bound order."""

from dataclasses import replace
from unittest.mock import MagicMock

import pytest

from immich_memories.analysis.runtime.plan import EditorialSelection
from immich_memories.api.models import AssetType
from immich_memories.config.loader import Config
from immich_memories.generate import GenerationParams
from immich_memories.generate_clips import extract_clips
from immich_memories.generate_timeline import apply_final_content_budget, validate_certified_content
from immich_memories.processing.assembly_config import AssemblyClip
from immich_memories.processing.editorial_timing import (
    bind_editorial_timeline,
    prepare_certified_timeline,
    timing_policy_for_params,
)
from immich_memories.processing.live_material import LiveRenderMaterial, LiveSourceEntry
from tests.conftest import make_clip


def _bound_params(tmp_path, kinds=("still", "live-still", "video", "live-motion")):
    clips = []
    for index, kind in enumerate(kinds):
        clip = make_clip(f"source-{index}", duration=3.5)
        if kind != "video":
            clip.asset.type = AssetType.IMAGE
        if kind.startswith("live-"):
            clip.asset.live_photo_video_id = f"companion-{index}"
        if kind == "live-motion":
            material = LiveRenderMaterial(
                (
                    LiveSourceEntry(
                        clip.asset.id,
                        clip.asset.live_photo_video_id,
                        0.0,
                        0.0,
                        3.5,
                    ),
                )
            )
            clip.live_burst_still_ids = list(material.still_ids)
            clip.live_burst_video_ids = list(material.video_ids)
            clip.live_burst_trim_points = list(material.trim_points)
            clip.live_burst_shutter_timestamps = list(material.shutter_timestamps)
            clip.live_burst_material = material.as_dict()
            clip.editorial_live_manifest = {
                "version": "editorial-live-render-v1",
                "material": material.as_dict(),
                "selected_interval": [0.0, 3.5],
            }
        clips.append(clip)
    params = GenerationParams(
        clips=clips,
        output_path=tmp_path / "out.mp4",
        config=Config(),
        client=MagicMock(),
        target_duration_seconds=60,
        memory_type="custom",
        clip_segments={clip.asset.id: (0.0, 3.5) for clip in clips},
        editorial_selections=tuple(
            EditorialSelection(
                clip.asset.id, 0.0, 3.5, "motion" if kind in {"video", "live-motion"} else "still"
            )
            for clip, kind in zip(clips, kinds, strict=True)
        ),
    )
    policy = timing_policy_for_params(params)
    carriers = [{"asset_id": clip.asset.id, "seconds": 3.5} for clip in clips]
    timeline = policy.resolve(carriers, {clip.asset.id: clip.asset for clip in clips})
    params.editorial_render_timing = bind_editorial_timeline(
        policy,
        timeline,
        [clip.asset.id for clip in clips],
    )
    return params


def _rendered(params, tmp_path):
    return [
        AssemblyClip(path=tmp_path / (clip.asset.id + ".mp4"), duration=3.5, asset_id=clip.asset.id)
        for clip in params.clips
    ]


def test_complete_mixed_selection_preserves_live_validation_contract(tmp_path):
    params = _bound_params(tmp_path)
    rendered = _rendered(params, tmp_path)
    assert validate_certified_content(params, rendered) == {"source-3"}
    assert apply_final_content_budget(params, rendered) == rendered
    rendered[-1] = replace(rendered[-1], duration=3.0)
    with pytest.raises(ValueError, match="Certified editorial Live interval changed"):
        validate_certified_content(params, rendered)


@pytest.mark.parametrize("change", ["missing", "extra", "duplicated", "order"])
def test_bound_render_rejects_membership_changes_with_a_specific_reason(tmp_path, change):
    params = _bound_params(tmp_path)
    rendered = _rendered(params, tmp_path)
    if change == "missing":
        rendered.pop(0)
        reason = "missing=\\['source-0'\\]"
    elif change == "extra":
        rendered.append(replace(rendered[0], asset_id="unselected"))
        reason = "extra=\\['unselected'\\]"
    elif change == "duplicated":
        rendered.append(rendered[0])
        reason = "duplicated=\\['source-0'\\]"
    else:
        rendered[0], rendered[1] = rendered[1], rendered[0]
        reason = "order_changed=True"
    with pytest.raises(ValueError, match=reason):
        apply_final_content_budget(params, rendered)


@pytest.mark.parametrize("lost_kind", ["still", "video"])
def test_a_source_that_cannot_be_prepared_leaves_a_shorter_film(tmp_path, monkeypatch, lost_kind):
    # One source is never a reason to lose the film (#2679): it leaves, and the film is
    # one clip shorter.
    params = _bound_params(tmp_path, (lost_kind, "still"))
    prepare_certified_timeline(params)
    monkeypatch.setattr(
        "immich_memories.photos.photo_pipeline.render_single_photo",
        _photo_unless(tmp_path, "source-0"),
    )
    monkeypatch.setattr(
        "immich_memories.generate_photos.detect_photo_resolution", lambda *_: (1920, 1080)
    )
    monkeypatch.setattr("immich_memories.generate_clips._download_video_path", lambda *_: None)
    rendered = extract_clips(params, None, tmp_path)
    assert [clip.asset_id for clip in rendered] == ["source-1"]
    assert params.departed_sources == ("source-0",)
    assert apply_final_content_budget(params, rendered) == rendered


@pytest.mark.parametrize("still_renders", [True, False])
def test_a_certified_live_that_fails_plays_its_still_or_leaves(
    tmp_path, monkeypatch, still_renders
):
    # The production shape of #2679: the companion's header declares more video than its
    # packets hold, so certification fails. The Live Photo holds its still for the slot;
    # if the still fails too, the film is one clip shorter.
    params = _bound_params(tmp_path, ("still", "live-motion"))
    prepare_certified_timeline(params)
    monkeypatch.setattr(
        "immich_memories.photos.photo_pipeline.render_single_photo",
        _photo_unless(tmp_path, None if still_renders else "source-1"),
    )
    monkeypatch.setattr(
        "immich_memories.generate_photos.detect_photo_resolution", lambda *_: (1920, 1080)
    )

    def fails_certification(*_args):
        raise ValueError("Editorial Live interval exceeds actual video source: {}")

    monkeypatch.setattr("immich_memories.generate_clips._download_video_path", fails_certification)
    rendered = extract_clips(params, None, tmp_path)
    if still_renders:
        assert [(clip.asset_id, clip.is_photo) for clip in rendered] == [
            ("source-0", True),
            ("source-1", True),
        ]
        assert rendered[1].duration == 3.5
        assert params.departed_sources == ()
    else:
        assert [clip.asset_id for clip in rendered] == ["source-0"]
        assert params.departed_sources == ("source-1",)
    assert validate_certified_content(params, rendered) == set()
    assert apply_final_content_budget(params, rendered) == rendered


def _photo_unless(tmp_path, failing_id):
    def render(**kwargs):
        if kwargs["asset"].id == failing_id:
            return None
        return AssemblyClip(
            path=tmp_path / "rendered.mp4",
            duration=kwargs["config"].duration,
            asset_id=kwargs["asset"].id,
            is_photo=True,
        )

    return render


def test_standalone_unbound_generation_keeps_its_partial_source_behavior(tmp_path):
    params = _bound_params(tmp_path, ("still", "video"))
    params.editorial_render_timing = None
    rendered = _rendered(params, tmp_path)[1:]
    assert validate_certified_content(params, rendered) == set()
