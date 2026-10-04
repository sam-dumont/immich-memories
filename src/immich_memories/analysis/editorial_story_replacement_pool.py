"""What a freed slot can be refilled from: a story's own moments, then other stories'.

The planner funds each story, admits its carriers, and only then knows which distinct moments,
in any story, never took a slot. This module turns that leftover into the pool the audience
gate and the final duplicate review draw a replacement from when a carrier is refused or removed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from immich_memories.analysis.editorial_carrier import carrier_row
from immich_memories.analysis.editorial_story_shortlist import DepictedChoice

if TYPE_CHECKING:
    from immich_memories.analysis.editorial_story_planner import StorySelection


def unfunded_pool(
    stories: Sequence[Mapping[str, Any]],
    choices_of: Mapping[str, list[DepictedChoice]],
    chosen_by_story: Mapping[str, list[str]],
) -> list[str]:
    """Every distinct moment that never took a slot, in the same priority order the stories
    were funded in: a story's own refill looks here once its own material runs out."""
    return [
        c.primary
        for s in stories
        for c in choices_of[s["key"]]
        if c.key not in chosen_by_story[s["key"]]
    ]


def _moments_of(selection: StorySelection, episode_key: str) -> Sequence[str]:
    for episode in selection.story.episodes:
        if episode.key == episode_key:
            return episode.moments
    return []


def alternatives_pool(
    selection: StorySelection,
    event_units: Mapping[str, list[dict]],
    anchor_label: Mapping[str, str],
) -> Callable[[Mapping[str, Any]], list[dict]]:
    """For the audience gate: when a carrier is held, offer the same moment's other pictures,
    then the story's unshown moments, then, once a story's own material runs out, other
    stories' moments that never took a slot, in the planner's own funding order.

    Each pool unit is bound to the context of the moment it actually shows: the spares of one
    carrier can come from another moment, family or even story, and a row that named the
    refused carrier there would misdescribe the picture the film then shows.
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

    def _row(a: str) -> dict | None:
        if a not in unit_by_asset:
            return None
        family, unit = unit_by_asset[a]
        if unit.get("moment") not in story_of_moment:
            return None
        return carrier_row(
            unit,
            family=family,
            anchor=anchor_label.get(family, family),
            story=story_of_moment[unit["moment"]],
            chapter=chapter_of_moment[unit["moment"]],
            line=selection.lines.get(a, ""),
        )

    def pool_for(carrier: Mapping[str, Any]) -> list[dict]:
        own = [
            row
            for a in selection.alternatives_of.get(carrier["asset_id"], [])
            if (row := _row(a)) is not None
        ]
        seen = {row["asset_id"] for row in own} | {carrier["asset_id"]}
        elsewhere = [
            row for a in selection.unfunded_pool if a not in seen and (row := _row(a)) is not None
        ]
        return own + elsewhere

    return pool_for
