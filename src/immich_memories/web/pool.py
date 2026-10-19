"""A cut's pool and the owner's word on its pictures, the same records `runs why` and `pictures` read."""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from immich_memories.analysis.corpus.picture_copies import picture_copies
from immich_memories.analysis.sources.snapshot import SNAPSHOT_NAME, sources_from_payload
from immich_memories.api.models import Asset, AssetType, VideoClipInfo
from immich_memories.config.loader import Config
from immich_memories.db import open_store
from immich_memories.operations import picture_holds
from immich_memories.operations.candidate_fates import CandidateFates
from immich_memories.operations.run_index import attempt_dir_for_run
from immich_memories.operations.storyboard import PLAN_FILE, PROJECTION_FILE, TRACE_FILE
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


@dataclass
class _PoolView:
    """A cut's pool, built once per version of its files: sorted pictures, fates, cut members."""

    assets: list[Asset]
    everything: int
    fates: CandidateFates
    in_cut: set[str]
    reachable: list[Asset] | None = None

    def pictures(self, *, reachable_only: bool) -> list[Asset]:
        if not reachable_only:
            return self.assets
        if self.reachable is None:
            self.reachable = [a for a in self.assets if self.fates.reachable(a.id)]
        return self.reachable


_VIEWS: OrderedDict[tuple[Path, tuple[object, ...]], _PoolView] = OrderedDict()
_VIEWS_KEPT = 4
_VIEWS_LOCK = threading.Lock()


def _stamps(attempt: Path) -> tuple[object, ...]:
    """Modification stamps of every file the pool is built from."""
    out: list[object] = []
    for name in (SNAPSHOT_NAME, PLAN_FILE, PROJECTION_FILE, TRACE_FILE):
        try:
            stat = (attempt / name).stat()
        except OSError:
            out.append(None)
        else:
            out.append((stat.st_mtime_ns, stat.st_size))
    return tuple(out)


def _pool_view(attempt: Path, snapshot: Path) -> _PoolView:
    """The pool of this attempt, rebuilt only when one of its files changed since last page."""
    key = (attempt, _stamps(attempt))
    with _VIEWS_LOCK:
        if (view := _VIEWS.get(key)) is not None:
            _VIEWS.move_to_end(key)
            return view
    payload = json.loads(snapshot.read_text())
    every_file = [_asset(source) for source in sources_from_payload(payload)]
    # One tile per picture: a copy (an album's downscale, a forwarded file) is its full-size file.
    copies = picture_copies(every_file)
    assets = sorted(
        (asset for asset in every_file if asset.id not in copies),
        key=lambda asset: (asset.file_created_at, asset.id),
    )
    fates = CandidateFates.read(attempt)
    view = _PoolView(
        assets,
        len(assets),
        fates,
        {shot.asset_id for shot in (fates.board.shots if fates.board else ())},
    )
    with _VIEWS_LOCK:
        _VIEWS[key] = view
        while len(_VIEWS) > _VIEWS_KEPT:
            _VIEWS.popitem(last=False)
    return view


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
    if attempt is None or snapshot is None or not snapshot.is_file():
        raise HTTPException(404, "This run kept no record of its pool.")
    view = _pool_view(Path(attempt), snapshot)
    assets = view.pictures(reachable_only=reachable_only)
    page = assets[offset : offset + limit]
    fates, in_cut = view.fates, view.in_cut
    # Only the page's pictures: the holds are read for these ids, not for the whole pool.
    holds = picture_holds.read(config, [asset.id for asset in page])
    return Pool(
        total=len(assets),
        outside=view.everything - len(assets),
        items=[
            PoolItem(
                asset_id=asset.id,
                taken=asset.local_taken_at.isoformat(),
                kind=_kind(asset),
                favourite=asset.is_favorite,
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
