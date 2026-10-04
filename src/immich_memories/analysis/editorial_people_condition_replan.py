"""The structure planner's bounded retry when a selected carrier fails the people condition.

The fetch already keeps the pool strict per picture, so this should never fire (#1954). If
it ever does, the fix is a real replan over the narrowed, violator-free pool, done BEFORE
the certified render timing is bound: every derived field (chapters, threads, the timing
binding) then comes out consistent, never a post-hoc rewrite of a carriers list whose
timing was already fixed (#1969).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from immich_memories.analysis.editorial_structure_contract import (
    StructurePlanningInput,
    StructurePlanningResult,
)

__all__ = ["enforce_people_condition"]


def enforce_people_condition(
    source: StructurePlanningInput,
    result: StructurePlanningResult,
    *,
    plan_once: Callable[[StructurePlanningInput], StructurePlanningResult],
) -> StructurePlanningResult:
    """One bounded retry: narrow the pool to non-violators, then replan exactly once."""
    violating = _violations_in(result)
    if not violating:
        return result
    narrowed = _without_violations(source, violating)
    if not _any_selectable(narrowed):
        return _refusal(result, violating)
    replanned = plan_once(narrowed)
    still_violating = _violations_in(replanned)
    if still_violating:
        return _refusal(replanned, violating | still_violating)
    return _with_warning(replanned, violating)


def _violations_in(result: StructurePlanningResult) -> frozenset[str]:
    violations = result.plan.get("intent_report", {}).get("violations", [])
    return frozenset(
        v["asset_id"] for v in violations if v.get("code") == "people_condition_violated"
    )


def _without_violations(
    source: StructurePlanningInput, violating: frozenset[str]
) -> StructurePlanningInput:
    """Narrow each moment to its non-violating candidates.

    A moment's selectable membership must stay nonempty and keep the wall's full alias
    order (`editorial_structure_contract._check_wall_membership`): when every one of a
    moment's candidates violates, its original (still-violating) set is kept rather than
    emptied, so that moment's own pick can still surface as "still violating" below -- a
    clear refusal, not a crash.
    """
    return replace(
        source,
        moment_asset_ids={
            alias: tuple(asset_id for asset_id in ids if asset_id not in violating) or ids
            for alias, ids in source.moment_asset_ids.items()
        },
    )


def _any_selectable(source: StructurePlanningInput) -> bool:
    return any(ids for ids in source.moment_asset_ids.values())


def _refusal(result: StructurePlanningResult, violating: frozenset[str]) -> StructurePlanningResult:
    """No picture is left once every carrier failing the people condition is excluded.

    Clears the carriers the violating pass selected and any timing bound to them: an
    `insufficient_material` status already empties the plan at render time
    (`editorial_runtime_backend._plan_from_structure_result`), so a stale carrier list or
    binding left in the record would describe a film that was never actually offered.
    """
    reason = (
        "No picture satisfies the requested people condition: "
        f"{len(violating)} selected picture(s) failed it and nothing else was offered."
    )
    report = result.plan["intent_report"] | {"status": "insufficient_material", "reason": reason}
    plan = result.plan | {
        "status": "insufficient_material",
        "intent_report": report,
        "carriers": [],
    }
    plan.pop("render_timing", None)
    return replace(result, plan=plan)


def _with_warning(
    result: StructurePlanningResult, dropped: frozenset[str]
) -> StructurePlanningResult:
    """Say what the replan above already fixed, so the run record and `runs why` show it."""
    return replace(result, plan=result.plan | {"people_condition_dropped": sorted(dropped)})
