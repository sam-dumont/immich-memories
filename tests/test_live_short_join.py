"""A burst too tight to stitch past the join minimum plays its kept picture's own clip (#1547)."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from itertools import pairwise

from immich_memories.analysis.editorial_source_route import project_source_rendering
from immich_memories.analysis.editorial_structure_planner import plan_structure
from immich_memories.analysis.motion_rendering import motion_renderings
from tests.annotation_rows import annotation_store
from tests.conftest import make_asset
from tests.test_editorial_duration_planner_integration import source
from tests.test_editorial_source_route import demand
from tests.test_live_clock_offsets_on_demand import live_carriers, ports

# Three shutters inside half a second, each companion 2.2 s long: they overlap so much that
# their stitch is barely longer than one of them, and under the 3.5 s join minimum.
SHUTTER_OFFSETS = (0.0, 0.2, 0.4)
COMPANION_SECONDS = 2.2


def shutter_offsets(video_ids):
    """Each join measures the true gap between its two shutters."""
    index = [int(v.rsplit("-", 1)[1]) % 3 for v in video_ids]
    return [SHUTTER_OFFSETS[b] - SHUTTER_OFFSETS[a] for a, b in pairwise(index)]


def tight_bursts(tmp_path, count, *, residual):
    """`count` three-picture bursts, an hour apart; the last picture of each is starred."""
    captured = source(tmp_path, seconds=15, pictures=3 * count)
    assets = dict(captured.assets)
    ordered = sorted(assets.values(), key=lambda asset: asset.file_created_at)
    start = ordered[0].file_created_at
    for index, asset in enumerate(ordered):
        burst, member = divmod(index, 3)
        asset.file_created_at = start + timedelta(hours=burst, seconds=SHUTTER_OFFSETS[member])
        asset.live_photo_video_id = f"video-{index}"
        asset.is_favorite = member == 2
    return replace(
        captured,
        assets=assets,
        companion_assets={
            asset.live_photo_video_id: make_asset(
                asset.live_photo_video_id, duration=COMPANION_SECONDS
            )
            for asset in assets.values()
        },
        motion_residuals={key: {"residual": residual} for key in assets},
        store=annotation_store(),
    )


def test_the_fixture_is_a_join_the_minimum_refuses(tmp_path):
    captured = tight_bursts(tmp_path, 1, residual=7.0)

    renderings = motion_renderings(
        list(captured.assets.values()),
        captured.config,
        companion_assets=captured.companion_assets,
        clock_offsets=shutter_offsets,
    )

    (burst,) = {id(r): r for r in renderings.values()}.values()
    assert len(burst.video_ids) == 3
    assert not burst.may_play


def test_a_tight_moving_burst_plays_the_starred_pictures_own_clip(tmp_path):
    captured = tight_bursts(tmp_path, 2, residual=7.0)
    plan = plan_structure(captured, ports(shutter_offsets)).plan

    carriers = live_carriers(plan)
    assert carriers, "the film keeps a burst"
    for carrier in carriers:
        starred = captured.assets[carrier["asset_id"]]
        assert starred.is_favorite
        assert carrier["kind"] == "live-motion"
        assert carrier["video_ids"] == [starred.live_photo_video_id]

    # The renderer re-derives the kept picture's clip and ships exactly that one.
    _, candidates = demand(list(captured.assets.values()))
    projected = project_source_rendering(
        plan["carriers"],
        candidates,
        config=captured.config,
        include_live_photos=True,
        companion_assets=captured.companion_assets,
        clock_offsets=shutter_offsets,
    )
    shipped = {row.clip.asset.id: row.clip for row in projected.candidates}
    for carrier in carriers:
        assert shipped[carrier["asset_id"]].live_burst_video_ids == carrier["video_ids"]


def test_a_tight_burst_that_barely_moves_stays_a_photograph(tmp_path):
    captured = tight_bursts(tmp_path, 2, residual=0.4)

    plan = plan_structure(captured, ports(shutter_offsets)).plan

    assert live_carriers(plan)
    assert all(c["kind"] == "live-still" for c in live_carriers(plan))
