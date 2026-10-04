"""A story's capacity: the moments its capture groups offer, and what it can show distinctly.

The capture-group pass sets a story's raw capacity before a single carrier is picked. Two of
those groups can still be the same scene shot twice; `distinct_choices` folds a further one
into the one it repeats, by the final duplicate review's own hash and scene rule, so a story's
real capacity is never inflated past what it can show without the review taking it back. The
fold only ever touches a story whose unfolded grant would exceed that real capacity: any story
whose grant was always going to fit keeps its exact, unfolded allocation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from immich_memories.analysis.editorial_story_lookalike import PairLooksAlike
from immich_memories.analysis.editorial_story_shortlist import (
    DepictedChoice,
    _capture_group_moments,
)
from immich_memories.analysis.editorial_story_slots import PartitionedSlots


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
            kept.append(choice)
        else:
            match.alternatives.extend(a for a in choice.members if a not in match.members)
    return kept


def capacity_choices(
    stories: Sequence[Mapping[str, Any]],
    story_units: Mapping[str, list[dict]],
    unit_by_asset: Mapping[str, tuple[Any, dict]],
    parts: PartitionedSlots,
    slots: int,
    hash_alike: PairLooksAlike | None,
    scene_alike: PairLooksAlike | None,
    **picking,
) -> tuple[dict[str, list[DepictedChoice]], dict[str, int]]:
    """Every story's capacity: the capture groups offered, and what is left once a further
    group that only repeats one kept is folded into it (`distinct_choices`) — but only for a
    story whose own unfolded grant would actually exceed that distinct count. A story whose
    grant was always going to fit inside its raw capacity (another story's weight, or its own,
    already capped it there) keeps today's exact, unfolded allocation untouched.
    """
    offered = _capture_group_choices(stories, story_units, **picking)
    groups_offered = {s["key"]: len(offered[s["key"]]) for s in stories}
    if hash_alike is None is scene_alike:
        return offered, groups_offered
    folded = {
        s["key"]: distinct_choices(
            offered[s["key"]], unit_by_asset, s["key"], hash_alike, scene_alike
        )
        for s in stories
    }
    if all(len(folded[s["key"]]) == len(offered[s["key"]]) for s in stories):
        return offered, groups_offered
    pre_grant, _partition_grants = parts.allocate(stories, offered, slots)
    gated = {
        s["key"]: folded[s["key"]]
        if pre_grant[s["key"]] > len(folded[s["key"]])
        else offered[s["key"]]
        for s in stories
    }
    return gated, groups_offered
