"""A cut's pool and the owner's word on its pictures, the same records `runs why` and `pictures` read."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from immich_memories.analysis.editorial_source_snapshot import SNAPSHOT_NAME, sources_from_payload
from immich_memories.analysis.picture_copies import picture_copies
from immich_memories.api.models import Asset, AssetType, VideoClipInfo
from immich_memories.config_loader import Config
from immich_memories.db import open_store
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


def _memory_people(payload: dict) -> set[str]:
    """The names or face ids the run was cut for: its people, or its grouped condition's leaves."""
    from immich_memories.api.person_expression import PersonExpression

    named = {str(value) for value in payload.get("people") or ()}
    if expression := payload.get("person_expression"):
        named |= set(PersonExpression.from_dict(expression).leaf_values)
    return named


def _same_episode(asset: Asset, people: set[str]) -> bool:
    """In the pool through its episode: none of the memory's people is recognised on it (#1438)."""
    return bool(people) and not any({face.id, face.name} & people for face in asset.people)


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
    reachable_only: bool = False,
) -> Pool:
    """Every picture the cut saw, in capture order, with its fate and whatever holds it."""
    attempt = attempt_dir_for_run(run_id, store=open_store(config))
    snapshot = Path(attempt) / SNAPSHOT_NAME if attempt else None
    if snapshot is None or not snapshot.is_file():
        raise HTTPException(404, "This run kept no record of its pool.")
    payload = json.loads(snapshot.read_text())
    people = _memory_people(payload)
    every_file = [_asset(source) for source in sources_from_payload(payload)]
    # One tile per picture: a copy (an album's downscale, a forwarded file) is its full-size file.
    copies = picture_copies(every_file)
    assets = sorted(
        (asset for asset in every_file if asset.id not in copies),
        key=lambda asset: (asset.file_created_at, asset.id),
    )
    fates = CandidateFates.read(attempt)
    everything = len(assets)
    if reachable_only:
        assets = [asset for asset in assets if fates.reachable(asset.id)]
    page = assets[offset : offset + limit]
    in_cut = {shot.asset_id for shot in (fates.board.shots if fates.board else ())}
    holds = picture_holds.read(config, [asset.id for asset in page])
    return Pool(
        total=len(assets),
        outside=everything - len(assets),
        items=[
            PoolItem(
                asset_id=asset.id,
                taken=asset.file_created_at.isoformat(),
                kind=_kind(asset),
                favourite=asset.is_favorite,
                same_episode=_same_episode(asset, people),
                in_cut=asset.id in in_cut,
                reachable=fates.reachable(asset.id),
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
