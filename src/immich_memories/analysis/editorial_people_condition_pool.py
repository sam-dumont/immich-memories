"""Apply the fetch's own people-condition rule once, to the whole pool, before planning.

The fetch already keeps the pool strict per picture (#1954), so this should never
exclude anything. If it ever does -- a defect elsewhere that let a non-matching picture
into the pool -- the fix is to narrow BEFORE any selection pass runs: the planner then
makes one consistent plan over material that already satisfies the condition, instead of
discovering a violation after chapters, timing and the rest were already built on it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from itertools import chain

from immich_memories.analysis.editorial_structure_contract import (
    StructurePlanningInput,
    StructurePlanningResult,
)
from immich_memories.analysis.person_presence import present_on_assets

__all__ = [
    "NarrowedPool",
    "exclude_people_condition_violators",
    "with_people_condition_exclusion",
]


@dataclass(frozen=True)
class NarrowedPool:
    source: StructurePlanningInput
    excluded: frozenset[str]
    # What `facts.source_assets` should report: the evidence `len(source.assets)` always
    # counted (companions and unselectable context included, by existing design) minus
    # only what the people condition excluded here. Equals `len(source.assets)` whenever
    # nothing was excluded, so an unrelated run's count never moves.
    pool_size: int


def exclude_people_condition_violators(source: StructurePlanningInput) -> NarrowedPool:
    """Every moment, narrowed to the candidates whose own faces satisfy the condition."""
    condition = source.case.resolved_person_condition
    all_ids = frozenset(chain.from_iterable(source.moment_asset_ids.values()))
    if condition is None or not all_ids:
        return NarrowedPool(source, frozenset(), len(source.assets))
    held = present_on_assets(
        [source.assets[asset_id] for asset_id in all_ids if asset_id in source.assets],
        condition,
        face_accounts=source.case.face_accounts,
    )
    violating = all_ids - held
    if not violating:
        return NarrowedPool(source, frozenset(), len(source.assets))
    narrowed_moments = _without(source.moment_asset_ids, violating)
    pool_size = len(source.assets) - len(violating)
    return NarrowedPool(replace(source, moment_asset_ids=narrowed_moments), violating, pool_size)


def _without(
    moment_asset_ids: Mapping[str, tuple[str, ...]], violating: frozenset[str]
) -> dict[str, tuple[str, ...]]:
    """Drop every violator; a moment left with none is kept as an empty entry (#1954).

    The wall already names every moment by alias in a fixed order
    (`editorial_structure_contract._check_wall_membership`), so a moment cannot be
    removed outright -- only emptied of what it may offer a selector.
    """
    return {
        alias: tuple(asset_id for asset_id in ids if asset_id not in violating)
        for alias, ids in moment_asset_ids.items()
    }


def with_people_condition_exclusion(
    result: StructurePlanningResult, excluded: frozenset[str]
) -> StructurePlanningResult:
    """Say what was left out before planning, and specialise an otherwise-empty cut's reason.

    The people check inside `build_result` (`editorial_structure_record._contract_check`)
    is a pure assertion now: every candidate it sees already satisfies the condition, so
    it should report no violation. This only announces the exclusion that ran first.
    """
    plan = result.plan | {"people_condition_excluded": sorted(excluded)}
    if not plan["carriers"]:
        reason = (
            "No picture satisfies the requested people condition: "
            f"{len(excluded)} picture(s) were left out before planning, and nothing else "
            "was offered."
        )
        plan = plan | {"intent_report": plan["intent_report"] | {"reason": reason}}
    return replace(result, plan=plan)
