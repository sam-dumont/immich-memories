"""An owner's edits to a saved cut, kept as numbered revisions in the run's attempt directory.

A revision never selects anything. It removes shots, trims a video's interval, changes how long
a still holds, swaps a shot for another picture of the same moment the planner recorded, or adds a
picture from the cut's pool. It is the owner's last pass: the film plays what they decided, longer
or shorter than the cut, with no detector or hold standing in the way. Every save is a new file,
so earlier revisions stay readable. The store moves to Postgres with #871.
"""

from __future__ import annotations

import json
import os
import statistics
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from immich_memories.analysis.editorial_source_snapshot import SNAPSHOT_NAME, load_sources
from immich_memories.api.models import Asset, AssetType, VideoClipInfo
from immich_memories.operations.storyboard import (
    Storyboard,
    moment_alternatives,
    read_storyboard,
    source_intervals,
)
from immich_memories.processing.editorial_owner_edits import review_interval

REVISIONS_DIR = "revisions"
_VERSION = 1


class RevisionRefused(ValueError):
    """The edits would not render: the message says which one and why."""


@dataclass(frozen=True)
class CutEdits:
    removed: tuple[str, ...] = ()
    segments: Mapping[str, tuple[float, float]] = field(default_factory=dict)
    swaps: Mapping[str, str] = field(default_factory=dict)
    added: tuple[str, ...] = ()


@dataclass(frozen=True)
class CutRevision:
    number: int
    created_at: str
    edits: CutEdits
    content_seconds: float


_STILL_SECONDS = 3.0
_MOTION_SECONDS = 4.0


def added_hold(shots: Iterable[tuple[float, bool]], asset: Asset) -> tuple[float, bool]:
    """How long an added picture plays, and whether it plays as motion.

    It takes the cut's own measure (`shots` as seconds and whether each moves): a photo holds as
    long as the cut's stills, a video or a Live Photo plays as long as the cut's moving shots,
    never longer than the video itself.
    """
    motion = asset.type == AssetType.VIDEO or bool(asset.live_photo_video_id)
    like = [seconds for seconds, moving in shots if moving == motion]
    seconds = statistics.median(like) if like else (_MOTION_SECONDS if motion else _STILL_SECONDS)
    if asset.type == AssetType.VIDEO and asset.duration_seconds:
        seconds = min(seconds, asset.duration_seconds)
    return round(seconds, 2), motion


def pool_assets(attempt_dir: Path) -> dict[str, Asset]:
    """Every picture the cut saw, by id: what an owner may add to it."""
    snapshot = Path(attempt_dir) / SNAPSHOT_NAME
    if not snapshot.is_file():
        return {}
    return {
        asset.id: asset
        for source in load_sources(snapshot)
        for asset in [source.asset if isinstance(source, VideoClipInfo) else source]
    }


def _content_seconds(
    board: Storyboard,
    edits: CutEdits,
    intervals: Mapping[str, tuple[float, float]],
    pool: Mapping[str, Asset],
) -> float:
    """The seconds the renderer will count: recorded intervals, not the squeezed storyboard."""
    total = 0.0
    for asset_id in edits.added:
        added = edits.segments.get(asset_id)
        measure = ((shot.seconds, shot.motion) for shot in board.shots)
        total += added[1] - added[0] if added else added_hold(measure, pool[asset_id])[0]
    for shot in board.shots:
        if shot.asset_id in edits.removed:
            continue
        playing = edits.swaps.get(shot.asset_id, shot.asset_id)
        recorded = intervals.get(shot.asset_id, (0.0, shot.seconds))
        start, end = edits.segments.get(playing, (0.0, recorded[1] - recorded[0]))
        total += end - start
    return round(total, 2)


def _as_dict(revision: CutRevision) -> dict[str, Any]:
    return {
        "version": _VERSION,
        "number": revision.number,
        "created_at": revision.created_at,
        "removed": list(revision.edits.removed),
        "segments": {key: list(value) for key, value in revision.edits.segments.items()},
        "swaps": dict(revision.edits.swaps),
        "added": list(revision.edits.added),
        "content_seconds": revision.content_seconds,
    }


def _from_dict(record: Mapping[str, Any]) -> CutRevision:
    return CutRevision(
        number=int(record["number"]),
        created_at=str(record["created_at"]),
        edits=CutEdits(
            removed=tuple(record.get("removed") or ()),
            segments={
                key: (float(a), float(b)) for key, (a, b) in (record.get("segments") or {}).items()
            },
            swaps=dict(record.get("swaps") or {}),
            added=tuple(record.get("added") or ()),
        ),
        content_seconds=float(record["content_seconds"]),
    )


def read_revisions(attempt_dir: Path) -> list[CutRevision]:
    """Every saved revision of this cut, oldest first."""
    folder = Path(attempt_dir) / REVISIONS_DIR
    if not folder.is_dir():
        return []
    return [
        _from_dict(json.loads(path.read_text())) for path in sorted(folder.glob("*.private.json"))
    ]


def _write(folder: Path, revision: CutRevision) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{revision.number:04d}.private.json"
    if target.exists():
        raise RevisionRefused(f"Revision {revision.number} already exists")
    handle, temporary = tempfile.mkstemp(dir=folder, suffix=".tmp")
    with os.fdopen(handle, "w") as stream:
        json.dump(_as_dict(revision), stream, indent=2)
    os.replace(temporary, target)


def _checked_additions(board: Storyboard, edits: CutEdits, pool: Mapping[str, Asset]) -> None:
    in_cut = {shot.asset_id for shot in board.shots} | set(edits.swaps.values())
    for asset in edits.added:
        if asset in in_cut:
            raise RevisionRefused(f"{asset} is already in the cut")
        if asset not in pool:
            raise RevisionRefused(f"{asset} is not in this cut's pool")
    if len(set(edits.added)) != len(edits.added):
        raise RevisionRefused("A picture is added twice")


def _checked(
    attempt_dir: Path, board: Storyboard, edits: CutEdits, pool: Mapping[str, Asset]
) -> None:
    """Only what the renderer cannot play is refused; length is the owner's call."""
    _checked_additions(board, edits, pool)
    in_cut = {shot.asset_id for shot in board.shots}
    siblings = moment_alternatives(attempt_dir)
    for asset in (*edits.removed, *edits.swaps):
        if asset not in in_cut:
            raise RevisionRefused(f"{asset} is not in this cut")
    for asset, replacement in edits.swaps.items():
        if replacement not in siblings.get(asset, ()):
            raise RevisionRefused(f"{replacement} is not another picture of that moment")
    playing = {edits.swaps.get(asset, asset) for asset in in_cut - set(edits.removed)} | set(
        edits.added
    )
    for asset, interval in edits.segments.items():
        if asset not in playing:
            raise RevisionRefused(f"{asset} is not in this cut")
        try:
            review_interval(interval)
        except ValueError as error:
            raise RevisionRefused(str(error)) from error


def save_revision(attempt_dir: Path, edits: CutEdits) -> CutRevision:
    """Check the edits against the saved cut and keep them as the next revision.

    The checks are the renderer's own: a picture outside the cut or its pool, a trim the renderer
    would refuse, or a swap to a picture the planner never kept for that moment. Length is not
    checked: the film grows or shrinks to what the owner kept. A refused revision writes nothing.
    """
    board = read_storyboard(Path(attempt_dir))
    if board is None:
        raise RevisionRefused("This run left no saved cut to revise")
    pool = pool_assets(Path(attempt_dir)) if edits.added else {}
    _checked(Path(attempt_dir), board, edits, pool)
    revision = CutRevision(
        number=len(read_revisions(attempt_dir)) + 1,
        created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        edits=edits,
        content_seconds=_content_seconds(board, edits, source_intervals(Path(attempt_dir)), pool),
    )
    _write(Path(attempt_dir) / REVISIONS_DIR, revision)
    return revision
