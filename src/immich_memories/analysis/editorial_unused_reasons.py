"""The planning rule that left each unused picture of a funded story out of the cut (#2211).

Every picture of a story the planner read either carries a shot or was passed over by one rule
of the plan. The pool and `runs why` print that rule, so "kept by every pass, not used in the
plan" is left for a picture no story ever held.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import Any

from immich_memories.analysis.editorial_story_shortlist import DepictedChoice
from immich_memories.planning.distinct_shots import PICTURES_PER_BEAT

NOT_STANDING = "it does not stand on its own as a picture of its story"
REPEAT = "it repeats a picture already in the cut"
CROWDED = "its place already holds its share of the film"
SPENT = "the film's content seconds were spent before its turn"
NOT_ITS_OWN_SHOT = (
    "it is not its own shot: a moment earns one shot for every "
    f"{PICTURES_PER_BEAT} distinct pictures, or one every five minutes"
)
UNWEIGHED = "its story weighs nothing: no shot is asked of it"
FEWER_SHOTS = "its story earned fewer shots than it has moments"


def unused_reasons(
    stories: Sequence[Mapping[str, Any]],
    story_units: Mapping[str, Sequence[Mapping[str, Any]]],
    choices_of: Mapping[str, Sequence[DepictedChoice]],
    *,
    carried: Collection[str],
    failed_standing: Collection[str],
    context_rejected: Collection[str],
    refused: Sequence[Mapping[str, Any]],
    depth_refused: Sequence[Mapping[str, Any]],
    film_full: bool,
) -> dict[str, str]:
    """A reason for every unused picture of a story, by the rule that passed it over."""
    refusals = {str(row["asset_id"]): CROWDED if "crowds" in row else REPEAT for row in refused}
    refusals |= {str(row["asset_id"]): REPEAT for row in depth_refused}
    standing = set(failed_standing) | set(context_rejected)
    reasons: dict[str, str] = {}
    for story in stories:
        key = story["key"]
        moments = {asset: choice for choice in choices_of.get(key, ()) for asset in choice.members}
        for unit in story_units.get(key, ()):
            asset = str(unit["asset_id"])
            if asset in carried:
                continue
            choice = moments.get(asset)
            sibling = choice is not None and any(a in carried for a in choice.members)
            reasons[asset] = (
                refusals.get(asset)
                or (NOT_STANDING if asset in standing else None)
                or _by_the_plan(story, sibling=sibling, film_full=film_full)
            )
    return reasons


def _by_the_plan(story: Mapping[str, Any], *, sibling: bool, film_full: bool) -> str:
    if sibling:
        return NOT_ITS_OWN_SHOT if not film_full else SPENT
    if story.get("weight") == "none":
        return UNWEIGHED
    return SPENT if film_full else FEWER_SHOTS


def unused_by_the_plan(admission, gate, stories, story_units, choices_of) -> dict[str, str]:
    """`unused_reasons` read off a finished admission and its standing gate."""
    return unused_reasons(
        stories,
        story_units,
        choices_of,
        carried={c["asset_id"] for c in admission.carriers},
        failed_standing=admission.failed_standing,
        context_rejected={asset for _story, asset in gate.context_rejected},
        refused=admission.lookalike.refused,
        depth_refused=admission.lookalike.depth["refused"],
        film_full=admission.film_full,
    )
