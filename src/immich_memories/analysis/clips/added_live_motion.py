"""Whether a Live Photo the owner adds in review plays as motion, decided as a cut decides it.

The added picture is stitched with its nearby Live Photos (`cluster_live_photos` decides
"nearby"). The stitch plays when it lasts the motion floor and moves; when the joins refuse or
the stitch falls short, the picture's own clip gets the same question. Anything else is the
picture's still (#2453).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Any

from immich_memories.analysis.clips.budget import RESIDUAL_MIN
from immich_memories.analysis.clips.motion_rendering import (
    ClockOffsetProbe,
    MotionRendering,
    motion_renderings,
)
from immich_memories.api.models import Asset, AssetType


def added_live_motion(
    asset: Asset,
    config: Any,
    *,
    nearby: Callable[[Asset], Sequence[Asset]],
    companion: Callable[[str], Asset | None],
    clock_offsets: Callable[[Mapping[str, Asset]], ClockOffsetProbe] | None,
    residual: Callable[[str], float | None],
) -> MotionRendering | None:
    """The motion an added Live Photo plays, or None when it plays as its still.

    `nearby` lists the pictures shot around it, `companion` reads a Live Photo's video,
    `clock_offsets` builds the join measurement over those videos and `residual` measures how
    much one video moves. Only a clip that may play is measured.
    """
    if asset.type != AssetType.IMAGE or not asset.live_photo_video_id:
        return None
    live = {
        picture.id: picture
        for picture in (asset, *nearby(asset))
        if picture.type == AssetType.IMAGE and picture.live_photo_video_id
    }
    companions = _companions(live.values(), companion)
    if asset.live_photo_video_id not in companions:
        return None
    probe = clock_offsets(companions) if clock_offsets is not None else None
    for rendering in _offers(asset, list(live.values()), config, companions, probe):
        if rendering.may_play:
            return rendering if _moves(rendering, residual) else None
    return None


def _companions(pictures: Any, companion: Callable[[str], Asset | None]) -> dict[str, Asset]:
    found: dict[str, Asset] = {}
    for picture in pictures:
        video = companion(picture.live_photo_video_id)
        if video is not None and video.id == picture.live_photo_video_id:
            found[video.id] = video
    return found


def _offers(
    asset: Asset,
    live: list[Asset],
    config: Any,
    companions: Mapping[str, Asset],
    probe: ClockOffsetProbe | None,
) -> Iterator[MotionRendering]:
    """The stitch with the nearby Live Photos first, then the picture's own clip."""
    stitched = motion_renderings(
        live, config, companion_assets=companions, clock_offsets=probe
    ).get(asset.id)
    if stitched is not None:
        yield stitched
    if stitched is None or len(stitched.still_ids) > 1:
        own = motion_renderings([asset], config, companion_assets=companions).get(asset.id)
        if own is not None:
            yield own


def _moves(rendering: MotionRendering, residual: Callable[[str], float | None]) -> bool:
    """The motion discriminant: the most any of its videos moves, against the residual bar."""
    measured = [value for video in rendering.video_ids if (value := residual(video)) is not None]
    return bool(measured) and max(measured) >= RESIDUAL_MIN
