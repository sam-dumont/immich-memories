"""The storyboard of a rendered film: its cut, with the owner's review edits when it had some.

A film rendered from a saved revision plays the cut less what the owner removed, with their
swaps, trims and additions. The edits it was rendered with are banked per film
(`store/owner_edits.py`); this lays them over the cut's plan and projection so the storyboard
reads what the film plays, timed the same way `read_storyboard` times the cut.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from immich_memories.operations.cut_revisions import added_hold, pool_assets
from immich_memories.operations.storyboard import (
    MOTION_KINDS,
    PLAN_FILE,
    PROJECTION_FILE,
    Storyboard,
    storyboard_from_plan,
)

if TYPE_CHECKING:
    from immich_memories.api.models import Asset

ADDED_REASON = "Added by you"


def film_storyboard(attempt_dir: Path, edits: Mapping[str, Any] | None) -> Storyboard | None:
    """The cut in `attempt_dir` as a film with these review `edits` plays it.

    `edits` is the record `project_editorial_owner_edits` built for the film; None reads the
    cut as chosen. None comes back when the attempt left no plan.
    """
    plan_path = Path(attempt_dir) / PLAN_FILE
    if not plan_path.is_file():
        return None
    plan = json.loads(plan_path.read_text())
    projection_path = Path(attempt_dir) / PROJECTION_FILE
    projection = json.loads(projection_path.read_text()) if projection_path.is_file() else {}
    if edits:
        plan, projection = _revised(Path(attempt_dir), plan, projection, edits)
    return storyboard_from_plan(plan, projection)


def _revised(
    attempt_dir: Path,
    plan: Mapping[str, Any],
    projection: Mapping[str, Any],
    edits: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    swaps = {row["original"]: row["replacement"] for row in edits.get("replacements") or ()}
    added = list(edits.get("added_asset_ids") or ())
    intervals = dict(projection.get("intervals") or {})
    pool = pool_assets(attempt_dir) if swaps or added else {}
    rows = _kept_rows(plan, set(edits.get("removed_asset_ids") or ()), swaps, intervals, pool)
    for trim in edits.get("interval_edits") or ():
        intervals[str(trim["asset_id"])] = list(trim["selected_interval"])
    rows += _added_rows(rows, added, intervals, pool)
    # The owner's edits are the last pass: the film grows to hold what they kept, unsqueezed.
    content = round(sum(_seconds(row, intervals) for row in rows), 2)
    realization = {**(plan.get("duration_realization") or {}), "content_budget_seconds": content}
    revised = {**plan, "carriers": rows, "duration_realization": realization}
    return revised, {**projection, "intervals": intervals}


def _kept_rows(
    plan: Mapping[str, Any],
    removed: set[str],
    swaps: Mapping[str, str],
    intervals: dict[str, Any],
    pool: Mapping[str, Asset],
) -> list[dict[str, Any]]:
    """The cut's rows less the removed ones, a swapped shot carrying its replacement."""
    rows = []
    for row in plan.get("carriers") or ():
        asset_id = str(row.get("asset_id"))
        if asset_id in removed:
            continue
        if asset_id in swaps:
            replacement = swaps[asset_id]
            row = {**row, "asset_id": replacement}
            if replacement in pool:
                row["taken"] = pool[replacement].local_taken_at.isoformat()
            if asset_id in intervals:
                intervals[replacement] = intervals.pop(asset_id)
        rows.append(dict(row))
    return rows


def _added_rows(
    rows: list[dict[str, Any]],
    added: list[str],
    intervals: Mapping[str, Any],
    pool: Mapping[str, Asset],
) -> list[dict[str, Any]]:
    """A row for each picture the owner added, held as long as the cut's own shots of its kind."""
    measure = [(_seconds(row, intervals), str(row.get("kind")) in MOTION_KINDS) for row in rows]
    out = []
    for asset_id in (asset_id for asset_id in added if asset_id in pool):
        seconds, motion = added_hold(measure, pool[asset_id])
        out.append(
            {
                "asset_id": asset_id,
                "taken": pool[asset_id].local_taken_at.isoformat(),
                "kind": "video" if motion else "still",
                "seconds": seconds,
                "why": ADDED_REASON,
            }
        )
    return out


def _seconds(row: Mapping[str, Any], intervals: Mapping[str, Any]) -> float:
    bounds = intervals.get(str(row.get("asset_id")))
    if isinstance(bounds, list | tuple) and len(bounds) == 2:
        return float(bounds[1]) - float(bounds[0])
    return float(row.get("seconds") or 0.0)
