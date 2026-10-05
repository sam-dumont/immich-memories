"""A story's capacity: the moments its capture groups offer, and what it can show distinctly.

The capture-group pass sets a story's raw capacity before a single carrier is picked. Two of
those groups can still be the same scene shot twice; `distinct_choices` folds a further one
into the one it repeats, by the final duplicate review's own hash and scene rule, so a story's
real capacity is never inflated past what it can show without the review taking it back.

The fold only ever reduces the folded story's own grant. The slack it frees is handed, one
moment at a time and in the planner's own funding order, to a weighed story that still has
unused raw capacity — never to a story already granted its whole raw capacity, whatever its
weight tier did to reach that. `parts.allocate` is never re-run against a mix of folded and
unfolded capacities: doing that let one story's fold change a neighbour's grant through the
water-filling the weight tiers already settled, which is the one thing `capacity_choices`
must never do.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from immich_memories.analysis.editorial_story_lookalike import PairLooksAlike
from immich_memories.analysis.editorial_story_shortlist import (
    DepictedChoice,
    _capture_group_moments,
)
from immich_memories.analysis.editorial_story_slots import PartitionedSlots
from immich_memories.analysis.editorial_story_standing import WEIGHED_STORY_WEIGHTS


def _capture_group_choices(
    stories: Sequence[Mapping[str, Any]],
    story_units: Mapping[str, list[dict]],
    **picking,
) -> dict[str, list[DepictedChoice]]:
    """Capture groups establish story capacity before its candidates are shortlisted."""
    choices_of: dict[str, list[DepictedChoice]] = {}
    for s in stories:
        out = _capture_group_moments(story_units[s["key"]], **picking)
        for c in out:
            c.episode = s["key"]
        choices_of[s["key"]] = out
    return choices_of


def distinct_choices(
    choices: Sequence[DepictedChoice],
    unit_by_asset: Mapping[str, tuple[Any, dict]],
    story_key: str,
    hash_alike: PairLooksAlike | None,
    scene_alike: PairLooksAlike | None,
) -> list[DepictedChoice]:
    """A story's capacity is the moments it can show distinctly, by the same hash and scene
    rule the final duplicate review applies over the finished cut (``hash_alike`` is
    `editorial_final_hash_review.hash_repeat_relation`, the review's own `_Repeats._by_hash`,
    not a copy of it). A further capture group whose own primary frame already reads as a
    repeat of one kept folds into it, so its pictures stay reachable as depth, rather than
    claiming a slot the review would only take back once the cut is built.

    Every returned choice is a copy: the caller decides whether to use the fold at all, and
    the group it came from — ``choices`` itself, and the DepictedChoice objects in it — must
    stay exactly as offered either way.

    A starred frame is never folded into a plain one it would repeat: the favourite wins its
    moment, the same exemption `LookAlikeCheck.repeats` makes at pick time, and two starred
    frames close enough to be the owner's one "twin" moment are the final duplicate review's
    own call to make, over the finished cut, not a capacity question asked before a single
    carrier is picked.
    """
    if hash_alike is None is scene_alike:
        return list(choices)

    def as_carrier(asset_id: str) -> dict[str, Any]:
        _family, unit = unit_by_asset[asset_id]
        return {
            "asset_id": asset_id,
            "taken": unit["taken"],
            "kind": unit.get("kind"),
            "favourite": unit.get("favourite"),
            "story_episode": story_key,
        }

    def repeats(candidate: Mapping[str, Any], keeper: Mapping[str, Any]) -> bool:
        if candidate.get("favourite"):
            return False
        return bool(
            (hash_alike and hash_alike(candidate, keeper))
            or (scene_alike and scene_alike(candidate, keeper))
        )

    kept: list[DepictedChoice] = []
    for choice in choices:
        candidate = as_carrier(choice.primary)
        match = next((k for k in kept if repeats(candidate, as_carrier(k.primary))), None)
        if match is None:
            kept.append(replace(choice))
        else:
            match.alternatives = [
                *match.alternatives,
                *(a for a in choice.members if a not in match.members),
            ]
    return kept


def _spill_folded_slack(
    stories: Sequence[Mapping[str, Any]],
    pre_grant: Mapping[str, int],
    offered: Mapping[str, list[DepictedChoice]],
    distinct: Mapping[str, list[DepictedChoice]],
) -> tuple[dict[str, int], set[str]]:
    """Cap each over-granted story's own grant at its distinct count, and hand the total
    slack it frees, one moment at a time in funding order, to a weighed story that still has
    unused raw capacity. A story already granted its full raw capacity never receives any of
    it and never loses any of its own: this never re-asks `parts.allocate` with a different
    capacity for anyone, so no other story's grant can move because of this story's fold.
    """
    final_grant = dict(pre_grant)
    over_granted: set[str] = set()
    freed = 0
    for s in stories:
        key = s["key"]
        distinct_count = len(distinct[key])
        if pre_grant[key] > distinct_count:
            freed += pre_grant[key] - distinct_count
            final_grant[key] = distinct_count
            over_granted.add(key)
    recipients = [
        s
        for s in stories
        if s["weight"] in WEIGHED_STORY_WEIGHTS and final_grant[s["key"]] < len(offered[s["key"]])
    ]
    progressed = bool(recipients)
    while freed > 0 and progressed:
        progressed = False
        for s in recipients:
            if freed <= 0:
                break
            key = s["key"]
            if final_grant[key] < len(offered[key]):
                final_grant[key] += 1
                freed -= 1
                progressed = True
        recipients = [s for s in recipients if final_grant[s["key"]] < len(offered[s["key"]])]
    return final_grant, over_granted


def capacity_choices(
    stories: Sequence[Mapping[str, Any]],
    story_units: Mapping[str, list[dict]],
    unit_by_asset: Mapping[str, tuple[Any, dict]],
    parts: PartitionedSlots,
    slots: int,
    hash_alike: PairLooksAlike | None,
    scene_alike: PairLooksAlike | None,
    **picking,
) -> tuple[dict[str, list[DepictedChoice]], dict[str, int], frozenset[str]]:
    """Every story's capacity: the capture groups offered, what is left once a further group
    that only repeats one kept is folded into it (`distinct_choices`), and which stories the
    same scene question is worth asking again later, at depth.

    A story's own raw, unfolded capacity decides every story's grant first (`pre_grant`, the
    same `parts.allocate` call the rest of the film already runs). Only a story whose grant
    this way exceeds its distinct count is capped and folded; the slack it frees moves to a
    weighed story with unused raw room, in funding order (`_spill_folded_slack`), never by
    asking `parts.allocate` again with anyone's capacity changed.

    The third value is the set of stories a depth frame can still be refused on scene print
    alone (`LookAlikeCheck.shows_something_new`): the ones the fold touched, and the ones
    already granted their whole raw capacity, since a depth frame for either can only be a
    further picture of a moment already shown, never a distinct one. A story with capacity
    to spare never asked this of a depth frame before this existed, and still never does.
    """
    offered = _capture_group_choices(stories, story_units, **picking)
    groups_offered = {s["key"]: len(offered[s["key"]]) for s in stories}
    if hash_alike is None is scene_alike:
        return offered, groups_offered, frozenset()
    distinct = {
        s["key"]: distinct_choices(
            offered[s["key"]], unit_by_asset, s["key"], hash_alike, scene_alike
        )
        for s in stories
    }
    pre_grant, _partition_grants = parts.allocate(stories, offered, slots)
    saturated = frozenset(
        s["key"] for s in stories if pre_grant[s["key"]] == groups_offered[s["key"]]
    )
    if all(len(distinct[s["key"]]) == len(offered[s["key"]]) for s in stories):
        return offered, groups_offered, saturated
    final_grant, over_granted = _spill_folded_slack(stories, pre_grant, offered, distinct)
    gated = {
        s["key"]: (
            distinct[s["key"]]
            if s["key"] in over_granted
            # A recipient's own raw choices never changed; only how many of them it may use
            # did, so its pool is bounded there and nowhere else moves. A story neither folded
            # nor spilled into keeps its exact, untouched choices: this is the one guarantee
            # that matters most, since every other story in the film is one of these.
            else offered[s["key"]][: final_grant[s["key"]]]
            if final_grant[s["key"]] != pre_grant[s["key"]]
            else offered[s["key"]]
        )
        for s in stories
    }
    return gated, groups_offered, frozenset(over_granted) | saturated
