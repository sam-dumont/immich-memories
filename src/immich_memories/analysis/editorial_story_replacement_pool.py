"""What a freed slot can be refilled from: a story's own moments, then other stories'.

The planner funds each story, admits its carriers, and only then knows which distinct moments,
in any story, never took a slot. This module turns that leftover into the pool the audience
gate and the final duplicate review draw a replacement from when a carrier is refused or removed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from functools import partial
from typing import TYPE_CHECKING, Any

from immich_memories.analysis.editorial_carrier import carrier_row
from immich_memories.analysis.editorial_story_shortlist import DepictedChoice
from immich_memories.analysis.editorial_story_standing import WEIGHED_STORY_WEIGHTS

if TYPE_CHECKING:
    from immich_memories.analysis.editorial_story_planner import StorySelection

# How many of another story's unfunded moments the final duplicate review may ask the audience
# gate about for one removed carrier. On the FULL tier each ask can cost a model call; a library
# with thousands of unfunded moments must not turn one repeat into thousands of asks.
MAX_ELSEWHERE_OFFERS = 20


def unfunded_pool(
    stories: Sequence[Mapping[str, Any]],
    choices_of: Mapping[str, list[DepictedChoice]],
    chosen_by_story: Mapping[str, list[str]],
) -> list[str]:
    """Every distinct moment that never took a slot, in the same priority order the stories
    were funded in, from a weighed story only: a story the synthesis gave no weight is never
    the household's own account of the period, and a refill does not make it one."""
    return [
        c.primary
        for s in stories
        if s["weight"] in WEIGHED_STORY_WEIGHTS
        for c in choices_of[s["key"]]
        if c.key not in chosen_by_story[s["key"]]
    ]


def _moments_of(selection: StorySelection, episode_key: str) -> Sequence[str]:
    for episode in selection.story.episodes:
        if episode.key == episode_key:
            return episode.moments
    return []


def _unit_row(
    asset_id: str,
    *,
    unit_by_asset: Mapping[str, Any],
    story_of_moment: Mapping[Any, Any],
    chapter_of_moment: Mapping[Any, int],
    anchor_label: Mapping[str, str],
    lines: Mapping[str, str],
) -> dict | None:
    """The row a pool offer shows: the context of the moment it actually carries, never the
    refused carrier's, so a borrowed description never misdescribes the picture the film
    then shows."""
    if asset_id not in unit_by_asset:
        return None
    family, unit = unit_by_asset[asset_id]
    if unit.get("moment") not in story_of_moment:
        return None
    return carrier_row(
        unit,
        family=family,
        anchor=anchor_label.get(family, family),
        story=story_of_moment[unit["moment"]],
        chapter=chapter_of_moment[unit["moment"]],
        line=lines.get(asset_id, ""),
    )


def _elsewhere_offers(
    carrier: Mapping[str, Any],
    seen: set[str],
    *,
    unfunded_pool: Sequence[str],
    row_of: Callable[[str], dict | None],
    months_shown: set[str],
    partition_of: Callable[[str], str | None] | None,
) -> list[dict]:
    """Other stories' unfunded moments, filtered to the months and the partition a carrier's
    own spares already had to meet, bounded to `MAX_ELSEWHERE_OFFERS` moments."""
    carrier_partition = partition_of(str(carrier["taken"])) if partition_of else None

    def admissible(row: dict) -> bool:
        if row["taken"][:7] not in months_shown:
            return False
        return partition_of is None or partition_of(str(row["taken"])) == carrier_partition

    offers: list[dict] = []
    for asset_id in unfunded_pool:
        if len(offers) >= MAX_ELSEWHERE_OFFERS:
            break
        row = None if asset_id in seen else row_of(asset_id)
        if row is None or not admissible(row):
            continue
        offers.append(row)
        seen.add(asset_id)
    return offers


def alternatives_pool(
    selection: StorySelection,
    event_units: Mapping[str, list[dict]],
    anchor_label: Mapping[str, str],
    *,
    include_elsewhere: bool = False,
    partition_of: Callable[[str], str | None] | None = None,
    cut_carriers: Sequence[Mapping[str, Any]] | None = None,
) -> Callable[[Mapping[str, Any]], list[dict]]:
    """When a carrier is held, offer the same moment's other pictures, then the story's
    unshown moments.

    With ``include_elsewhere`` (the final duplicate review only: the audience gate's own
    ``apply_gate`` drops a carrier rather than reach past its own anchor), once a story's own
    material runs out the pool reaches into other stories' moments that never took a slot, in
    the planner's own funding order. An elsewhere offer is never from a month the film does
    not already show — ``cut_carriers`` is the finished cut at the point the caller runs its
    own review (after the audience gate and the timing trim, for the final duplicate review;
    selection's own carriers when the caller has no later cut, e.g. the audience gate's own
    narrower pool) — never from a different partition than the carrier it would replace when
    the product caps carriers per partition, and the pool stops after `MAX_ELSEWHERE_OFFERS`
    moments so one repeat cannot turn into an unbounded run of audience asks.
    """
    unit_by_asset = {u["asset_id"]: (f, u) for f, units in event_units.items() for u in units}
    # A unit row's moment is a loosely-typed field; the map keys are the story's moment ids.
    chapter_of_moment: dict[Any, int] = {
        moment: number
        for number, row in enumerate(selection.episodes, 1)
        for episode in row["day_episodes"]
        for moment in _moments_of(selection, episode)
    }
    story_of_moment = {
        moment: story
        for story in selection.story.stories
        for episode in story["episodes"]
        for moment in _moments_of(selection, episode)
    }
    shown = selection.carriers if cut_carriers is None else cut_carriers
    months_shown = {str(c.get("taken", ""))[:7] for c in shown}
    row_of = partial(
        _unit_row,
        unit_by_asset=unit_by_asset,
        story_of_moment=story_of_moment,
        chapter_of_moment=chapter_of_moment,
        anchor_label=anchor_label,
        lines=selection.lines,
    )

    def pool_for(carrier: Mapping[str, Any]) -> list[dict]:
        own = [
            row
            for a in selection.alternatives_of.get(carrier["asset_id"], [])
            if (row := row_of(a)) is not None
        ]
        if not include_elsewhere:
            return own
        seen = {row["asset_id"] for row in own} | {carrier["asset_id"]}
        return own + _elsewhere_offers(
            carrier,
            seen,
            unfunded_pool=selection.unfunded_pool,
            row_of=row_of,
            months_shown=months_shown,
            partition_of=partition_of,
        )

    return pool_for
