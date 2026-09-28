"""A picture the owner adds to a saved cut, made ready to play the way the cut's own shots are.

Nothing here judges the picture: the owner chose it. A video plays from its start, a Live Photo
plays its stitched motion (or holds its still when the motion cannot be stitched), a photo holds.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from immich_memories.analysis.editorial_planner import EditorialSelection
from immich_memories.api.models import Asset, AssetType, VideoClipInfo

if TYPE_CHECKING:
    from immich_memories.analysis.motion_rendering import MotionRendering

LiveMotion = Callable[[Asset], "MotionRendering | None"]


def _live(
    clip: VideoClipInfo, rendering: MotionRendering, seconds: float
) -> tuple[VideoClipInfo, EditorialSelection] | None:
    material = rendering.material
    if material is None:
        return None
    interval = material.selected_interval(min(seconds, material.duration_seconds))
    ready = clip.model_copy(
        update={
            "duration_seconds": rendering.duration_seconds,
            "live_burst_video_ids": list(rendering.video_ids),
            "live_burst_trim_points": list(rendering.trim_points),
            "live_burst_shutter_timestamps": list(rendering.shutter_timestamps),
            "live_burst_still_ids": list(rendering.still_ids),
            "live_burst_material": material.as_dict(),
            "editorial_live_manifest": {
                "version": "editorial-live-render-v1",
                "material": material.as_dict(),
                "selected_interval": list(interval),
            },
            "local_path": None,
        }
    )
    return ready, EditorialSelection(clip.asset.id, *interval, render_mode="motion")


def prepared_addition(
    clip: VideoClipInfo, seconds: float, *, motion: bool, live_motion: LiveMotion | None
) -> tuple[VideoClipInfo, EditorialSelection]:
    """The clip and the rendering decision an added picture plays with, for `seconds`."""
    asset = clip.asset
    if asset.type == AssetType.VIDEO:
        end = min(seconds, clip.duration_seconds) if clip.duration_seconds else seconds
        return clip, EditorialSelection(asset.id, 0.0, end, render_mode="motion")
    rendering = live_motion(asset) if motion and live_motion else None
    stitched = _live(clip, rendering, seconds) if rendering is not None else None
    if stitched is not None:
        return stitched
    still = clip.model_copy(update={"duration_seconds": seconds})
    return still, EditorialSelection(asset.id, 0.0, seconds, render_mode="still")
