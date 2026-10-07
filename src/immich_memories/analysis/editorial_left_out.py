"""Why the final cut left each picture out, in the words `runs why` and the pool print.

The planner's own stage drops everything it did not use. A picture a pass removed (the
family-viewing check, the duplicate review, the timing trim) keeps that pass's reason; the
rest were simply not used, and say that much rather than nothing.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from immich_memories.analysis.editorial_shareability import FAMILY, allowed

NOT_IN_PLAN = "kept by every pass, not used in the plan"

_LEVEL_WORDS = {"just_us": "just-us", "family": "family", "shareable": "shareable"}


def final_cut_notes(plan: Mapping[str, Any], lost_ids: Iterable[str]) -> dict[str, str]:
    """A reason for every picture in `lost_ids`, read from the finished plan."""
    share = plan.get("shareability") or {}
    audience = str(share.get("audience") or FAMILY)
    level = _LEVEL_WORDS.get(audience, audience)
    reasons: dict[str, str] = {}
    for asset_id, record in (share.get("verdicts") or {}).items():
        if isinstance(record, Mapping) and not allowed(str(record.get("verdict")), audience):
            why = record.get("why") or record.get("finding") or record.get("verdict")
            reasons[str(asset_id)] = f"the family-viewing check held it from a {level} film: {why}"
    for row in plan.get("cut_carriers") or ():
        if row.get("reason"):
            reasons[str(row["asset_id"])] = str(row["reason"])
    unused = NOT_IN_PLAN
    if not plan.get("carriers") and share.get("tightened"):
        unused = f"not used: the family-viewing check held back every shot this {level} film chose"
    by_rule = plan.get("left_out") or {}
    return {
        asset_id: reasons.get(asset_id) or by_rule.get(asset_id) or unused for asset_id in lost_ids
    }
