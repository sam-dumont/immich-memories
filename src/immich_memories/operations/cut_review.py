"""Recorded model proposals for the pictures being reviewed, without new inference."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

Decision = dict[str, str | int]

# A late fit check can take back a seated newcomer; the seat's own row still says "seated".
_REVOKED = "taken back by the fit check"


def _blank() -> Decision:
    return {
        "model_reason": "",
        "kept_reason": "",
        "proposed_asset_id": "",
        "offered_count": 0,
        "replacement_outcome": "",
        "replaced_asset_id": "",
        "seat": "",
    }


def read_cut_decisions(attempt_dir: Path) -> dict[str, Decision]:
    """Read saved model objections, protection reasons and seat outcomes, keyed by picture.

    A seated replacement is explained on the picture that took the seat, since the one it
    replaced is no longer in the film. An offer that did not survive is explained on the
    picture that stayed. An absent or unreadable pass adds nothing.
    """
    path = attempt_dir / "derived-decisions" / "thin-polish.private.json"
    if not path.is_file():
        return {}
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(record, dict):
        return {}
    verdicts: dict[str, dict[str, Any]] = record.get("verdicts", {})
    decisions = {asset_id: _verdict(row) for asset_id, row in verdicts.items()}
    revoked = set(record.get("revoked_by_the_fit_check", []))
    for slot in record.get("slots", []):
        _place_slot(decisions, slot, verdicts, revoked)
    return decisions


def _verdict(row: dict[str, Any]) -> Decision:
    return _blank() | {
        "model_reason": row.get("why", ""),
        "kept_reason": row.get("held_by", "") if row.get("protected") else "",
    }


def _place_slot(
    decisions: dict[str, Decision],
    slot: dict[str, Any],
    verdicts: dict[str, dict[str, Any]],
    revoked: set[str],
) -> None:
    replacing, chosen = slot.get("replacing", ""), slot.get("chosen", "")
    offered = int(slot.get("offered") or 0)
    outcome = _REVOKED if chosen in revoked else slot.get("outcome", "")
    if chosen and outcome == "seated":
        decisions[chosen] = _blank() | {
            "model_reason": verdicts.get(replacing, {}).get("why", ""),
            "replaced_asset_id": replacing,
            "offered_count": offered,
            "seat": slot.get("rule", ""),
        }
        return
    if replacing:
        decisions.setdefault(replacing, _blank()).update(
            proposed_asset_id=chosen,
            offered_count=offered,
            replacement_outcome=outcome,
        )
