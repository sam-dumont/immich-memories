"""Live Photo motion for the scripted editor, decided and projected the production way.

The scripted editor chooses which pictures ship; for a Live Photo it also has to say whether the
picture plays as motion, and a hermetic run has no model to ask. Nothing about that answer is
scripted here: the burst each still belongs to comes from `motion_renderings`, its joins from
the measured clock offsets (`BankedClockOffsets`) over the companion clips Immich serves, the
motion from the optical-flow residual (`measure_motion`) against the editor's own threshold, and
the clip assembly renders from `project_source_rendering`, the same projection the production
route ends with. What remains of the editor's decision is its rule, written out in
`_plays_as_motion` beside the code it mirrors.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any


def _plays_as_motion(rendering: Any, residual: float | None) -> bool:
    """`film.material.StructureMaterial._live_unit`: a rendering that may play,
    with measured motion at or above the residual threshold, plays; anything else stays a still.
    """
    from immich_memories.analysis.clips.budget import RESIDUAL_MIN

    return bool(rendering.may_play and residual is not None and residual >= RESIDUAL_MIN)


def live_projection(
    candidates: tuple[Any, ...],
    sources: Sequence[Any],
    *,
    config: Any,
    companions: Sequence[Any],
    fetch: Callable[[str], bytes],
    include_live_photos: bool,
    demand: Callable[[Sequence[Any]], tuple[Any, ...]],
    content_budget: Callable[[list[dict]], float | None] = lambda _carriers: None,
) -> tuple[tuple[Any, ...], tuple[Any, ...]] | None:
    """The kept clips and their render directives once Live motion is decided, or None when
    the cut holds no Live Photo that could play (the scripted cut then stands as it is).

    `demand` times extra sources the way the scripted editor times its own: a burst's other
    takes join the demand so the stitch can reach them, without becoming shots of their own.
    `content_budget` is the run's render budget for a set of carriers: a certified Live
    interval is never trimmed at the render, so, as the structure planner does, the cut is
    fitted to the budget here, by holding the other shots shorter.
    """
    from immich_memories.analysis.clips.live_clock_offsets import BankedClockOffsets
    from immich_memories.analysis.clips.motion_facts import measure_motion
    from immich_memories.analysis.clips.motion_rendering import motion_renderings
    from immich_memories.analysis.runtime.source_route import project_source_rendering
    from immich_memories.api.models import AssetType

    companion_assets = {companion.id: companion for companion in companions}
    stills = [
        asset
        for asset in (_asset_of(source) for source in sources)
        if asset.type == AssetType.IMAGE and asset.live_photo_video_id
    ]
    if not include_live_photos or not stills or not companion_assets:
        return None
    probe = BankedClockOffsets(store=None, companions=companion_assets, fetch=fetch)
    renderings = motion_renderings(
        stills, config, companion_assets=companion_assets, clock_offsets=probe
    )
    residuals: dict[str, float | None] = {}

    def residual(video_id: str) -> float | None:
        if video_id not in residuals:
            residuals[video_id] = measure_motion(fetch(video_id)).get("residual")
        return residuals[video_id]

    carriers: list[dict] = []
    members: set[str] = set()
    for row in candidates:
        rendering = renderings.get(row.clip.asset.id)
        measured = [residual(video_id) for video_id in rendering.video_ids] if rendering else []
        known = [value for value in measured if value is not None]
        if rendering is not None and _plays_as_motion(rendering, max(known, default=None)):
            carriers.append(_motion_carrier(row.clip.asset.id, rendering))
            members.update(rendering.still_ids)
        else:
            carriers.append(_plain_carrier(row))
    if not members:
        return None
    _fit(carriers, content_budget(carriers))
    by_id = {row.clip.asset.id: row for row in candidates}
    extra = [s for s in sources if _asset_of(s).id in members - set(by_id)]
    projected = project_source_rendering(
        carriers,
        (*candidates, *demand(extra)),
        config=config,
        include_live_photos=True,
        clock_offsets=probe,
        companion_assets=companion_assets,
    )
    shots = {carrier["asset_id"] for carrier in carriers}
    return (
        tuple(row for row in projected.candidates if row.clip.asset.id in shots),
        projected.plan.selections,
    )


def _fit(carriers: list[dict], budget: float | None) -> None:
    """Shorten every shot but the Live motion so the whole cut fits its content budget."""
    if budget is None:
        return
    fixed = sum(c["seconds"] for c in carriers if c["kind"] == "live-motion")
    free = [c for c in carriers if c["kind"] != "live-motion"]
    total = fixed + sum(c["seconds"] for c in free)
    if total <= budget or not free:
        return
    scale = max(0.0, budget - fixed) / sum(c["seconds"] for c in free)
    for carrier in free:
        seconds = max(0.5, int(carrier["seconds"] * scale * 100) / 100)
        carrier["seconds"] = seconds
        carrier["end_time"] = carrier["start_time"] + seconds


def _motion_carrier(asset_id: str, rendering: Any) -> dict:
    """A `live-motion` carrier row as the structure planner writes one."""
    from immich_memories.analysis.clips.budget import (
        MOTION_CAP_SECONDS,
        raw_centiseconds,
    )

    return {
        "asset_id": asset_id,
        "kind": "live-motion",
        "members": list(rendering.still_ids),
        "video_ids": list(rendering.video_ids),
        "trim_points": [list(pair) for pair in rendering.trim_points],
        "live_material": rendering.material.as_dict(),
        "seconds": raw_centiseconds(min(rendering.duration_seconds, MOTION_CAP_SECONDS)),
        "raw_seconds": raw_centiseconds(rendering.duration_seconds),
        "start_time": 0.0,
    }


def _plain_carrier(row: Any) -> dict:
    """A still or a video, timed as the scripted editor timed it."""
    from immich_memories.api.models import AssetType

    kind = "video" if row.clip.asset.type == AssetType.VIDEO else "still"
    return {
        "asset_id": row.clip.asset.id,
        "kind": kind,
        "seconds": round(row.end_time - row.start_time, 6),
        "start_time": row.start_time,
        "end_time": row.end_time,
    }


def _asset_of(source: Any) -> Any:
    from immich_memories.api.models import VideoClipInfo

    return source.asset if isinstance(source, VideoClipInfo) else source


def companions_of(source_pool: Any) -> Sequence[Any]:
    """The companion clips the source pool resolved for its Live Photos."""
    return tuple(getattr(source_pool, "companions", ()) or ())
