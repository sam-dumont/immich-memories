"""An owner's edits to a saved cut, kept as numbered revisions in the run's attempt directory.

A revision never selects anything. It removes shots, trims a video's interval, changes how long
a still holds, or swaps a shot for another picture of the same moment the planner recorded. Every
save is a new file, so earlier revisions stay readable. The store moves to Postgres with #871.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


@dataclass(frozen=True)
class CutRevision:
    number: int
    created_at: str
    edits: CutEdits
    content_seconds: float


def _content_seconds(
    board: Storyboard, edits: CutEdits, intervals: Mapping[str, tuple[float, float]]
) -> float:
    """The seconds the renderer will count: recorded intervals, not the squeezed storyboard."""
    total = 0.0
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


def _checked(attempt_dir: Path, board: Storyboard, edits: CutEdits) -> None:
    in_cut = {shot.asset_id for shot in board.shots}
    siblings = moment_alternatives(attempt_dir)
    for asset in (*edits.removed, *edits.swaps):
        if asset not in in_cut:
            raise RevisionRefused(f"{asset} is not in this cut")
    for asset, replacement in edits.swaps.items():
        if replacement not in siblings.get(asset, ()):
            raise RevisionRefused(f"{replacement} is not another picture of that moment")
    playing = {edits.swaps.get(asset, asset) for asset in in_cut - set(edits.removed)}
    for asset, interval in edits.segments.items():
        if asset not in playing:
            raise RevisionRefused(f"{asset} is not in this cut")
        try:
            review_interval(interval)
        except ValueError as error:
            raise RevisionRefused(str(error)) from error
    budget = board.content_budget_seconds
    seconds = _content_seconds(board, edits, source_intervals(attempt_dir))
    if budget is not None and seconds > budget + 1e-6:
        raise RevisionRefused(
            f"The edited cut needs {seconds:.1f} s of pictures and video; "
            f"the titles leave {budget:.1f} s"
        )


def save_revision(attempt_dir: Path, edits: CutEdits) -> CutRevision:
    """Check the edits against the saved cut and keep them as the next revision.

    The checks are the renderer's own: a picture outside the cut, a trim the renderer would
    refuse, a swap to a picture the planner never kept for that moment, or more seconds than the
    titles leave. A refused revision writes nothing.
    """
    board = read_storyboard(Path(attempt_dir))
    if board is None:
        raise RevisionRefused("This run left no saved cut to revise")
    _checked(Path(attempt_dir), board, edits)
    revision = CutRevision(
        number=len(read_revisions(attempt_dir)) + 1,
        created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        edits=edits,
        content_seconds=_content_seconds(board, edits, source_intervals(Path(attempt_dir))),
    )
    _write(Path(attempt_dir) / REVISIONS_DIR, revision)
    return revision
