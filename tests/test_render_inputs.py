"""A cut keeps the exact inputs its render used, so a later render starts from the same objects."""

from __future__ import annotations

from datetime import UTC, datetime

from immich_memories.analysis.editorial_planner import EditorialSelection
from immich_memories.api.models import AssetType
from immich_memories.processing.render_inputs import read_render_inputs, write_render_inputs
from tests.conftest import make_clip


def test_render_inputs_come_back_exactly_including_a_live_certificate(tmp_path):
    still = make_clip("still-1", duration=5, file_created_at=datetime(2024, 6, 1, tzinfo=UTC))
    still.asset.type = AssetType.IMAGE
    live = make_clip("live-1", duration=3, file_created_at=datetime(2024, 6, 2, tzinfo=UTC))
    live.asset.type = AssetType.IMAGE
    live.asset.live_photo_video_id = "live-1-motion"
    live.editorial_live_manifest = {
        "version": "editorial-live-render-v1",
        "selected_interval": [0, 2],
    }
    selections = (
        EditorialSelection("still-1", 0.0, 3.0, "still"),
        EditorialSelection("live-1", 0.0, 2.0, "motion"),
    )
    binding = {
        "policy": {"a": 1},
        "sha256": "abc",
        "source_ids": ["still-1", "live-1"],
        "timeline": {},
    }

    write_render_inputs(
        tmp_path, [still, live], selections, {"still-1": (0.0, 3.0), "live-1": (0.0, 2.0)}, binding
    )
    restored = read_render_inputs(tmp_path)

    assert restored is not None
    assert [clip.asset.id for clip in restored.clips] == ["still-1", "live-1"]
    assert restored.clips[1] == live
    assert restored.selections == selections
    assert restored.segments == {"still-1": (0.0, 3.0), "live-1": (0.0, 2.0)}
    assert restored.binding == binding


def test_a_cut_made_before_render_inputs_existed_reads_as_none(tmp_path):
    assert read_render_inputs(tmp_path) is None
