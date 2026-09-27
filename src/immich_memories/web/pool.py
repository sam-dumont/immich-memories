"""A cut's pool and the owner's word on its pictures, the same records `runs why` and `pictures` read."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from immich_memories.analysis.editorial_source_snapshot import SNAPSHOT_NAME, load_sources
from immich_memories.api.models import Asset, AssetType, VideoClipInfo
from immich_memories.config_loader import Config
from immich_memories.operations import picture_holds
from immich_memories.operations.candidate_fates import CandidateFates
from immich_memories.operations.run_index import attempt_dir_for_run
from immich_memories.store.owner_decisions import CLEARANCE_LEVELS, NEVER_USE
from immich_memories.web.dependencies import current_config
from immich_memories.web.schemas import Decision, Hold, Pool, PoolItem

router = APIRouter(prefix="/api/v1", tags=["pool"])

_LEVEL_OF = {decision: level for level, decision in CLEARANCE_LEVELS.items()}


def _decision(value: str | None) -> str | None:
    if value is None:
        return None
    return "never_use" if value == NEVER_USE else f"cleared:{_LEVEL_OF.get(value, value)}"


def _hold(hold: picture_holds.PictureHold) -> Hold:
    return Hold(
        decision=_decision(hold.decision), reasons=list(hold.reasons), can_clear=hold.can_clear
    )


def _asset(source: Asset | VideoClipInfo) -> Asset:
    return source.asset if isinstance(source, VideoClipInfo) else source


def _kind(asset: Asset) -> Literal["photo", "video", "live"]:
    if asset.type == AssetType.VIDEO:
        return "video"
    return "live" if asset.live_photo_video_id else "photo"


@router.get("/runs/{run_id}/pool", response_model=Pool)
def read_pool(
    run_id: str,
    config: Annotated[Config, Depends(current_config)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 120,
) -> Pool:
    """Every picture the cut saw, in capture order, with its fate and whatever holds it."""
    attempt = attempt_dir_for_run(config.cache.cache_path, run_id)
    snapshot = Path(attempt) / SNAPSHOT_NAME if attempt else None
    if snapshot is None or not snapshot.is_file():
        raise HTTPException(404, "This run kept no record of its pool.")
    assets = sorted(
        (_asset(source) for source in load_sources(snapshot)),
        key=lambda asset: (asset.file_created_at, asset.id),
    )
    page = assets[offset : offset + limit]
    fates = CandidateFates.read(attempt)
    in_cut = {shot.asset_id for shot in (fates.board.shots if fates.board else ())}
    holds = picture_holds.read(config, [asset.id for asset in page])
    return Pool(
        total=len(assets),
        items=[
            PoolItem(
                asset_id=asset.id,
                taken=asset.file_created_at.isoformat(),
                kind=_kind(asset),
                favourite=asset.is_favorite,
                in_cut=asset.id in in_cut,
                fate=fates.describe(asset.id),
                hold=_hold(holds[asset.id]),
            )
            for asset in page
        ],
    )


@router.post("/pictures/{asset_id}/decision", response_model=Hold)
def decide(
    asset_id: str, decision: Decision, config: Annotated[Config, Depends(current_config)]
) -> Hold:
    """The owner's word on one picture, kept across runs: never use it, clear its hold, or forget."""
    if decision.action == "never_use":
        picture_holds.never_use(config, asset_id, via="web")
    elif decision.action == "clear":
        picture_holds.clear_hold(config, asset_id, via="web", level=decision.level)
    else:
        picture_holds.forget(config, asset_id)
    return _hold(picture_holds.read(config, [asset_id])[asset_id])
