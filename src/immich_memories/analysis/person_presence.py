"""Who is in a picture, for a film about people: whoever is recognised in its episode.

Immich answers "is this person here" per frame, and a face goes unrecognised for people
who are really there: the back of a head, a baby feeding against a chest, a child across
the garden. So a person counts as present in every picture of an episode (the 90-minute
grouping every film is cut from) where their face is recognised at least once, and in no
picture outside it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from immich_memories.analysis.moment_grouping import (
    EPISODE_WINDOW_MINUTES,
    group_by_time_and_place,
)
from immich_memories.api.models import Asset
from immich_memories.api.person_expression import PersonExpression


def people_condition(
    people: Sequence[str],
    person_match: Literal["and", "or"],
    expression: PersonExpression | None,
) -> PersonExpression | None:
    """The run's people as one condition, or None when the film is not about anyone."""
    if expression is not None:
        return expression
    leaves = tuple(PersonExpression("person", value=name) for name in people)
    if not leaves:
        return None
    if len(leaves) == 1:
        return leaves[0]
    return PersonExpression("all" if person_match == "and" else "any", children=leaves)


def present_in_episodes(assets: Sequence[Asset], condition: PersonExpression) -> frozenset[str]:
    """Every picture whose episode satisfies ``condition``.

    A leaf holds in an episode when that name is recognised on any of its pictures, so
    ``all`` asks for every named person somewhere in the episode, not in one frame.
    Names compare without case, as the CLI's person lookup does.
    """
    episodes = group_by_time_and_place(assets, window_minutes=EPISODE_WINDOW_MINUTES)
    held_by_name: dict[str, set[int]] = {}
    for index, episode in enumerate(episodes):
        for asset in episode:
            for person in asset.people:
                if person.name:
                    held_by_name.setdefault(person.name.casefold(), set()).add(index)
    held = condition.evaluate(lambda name: held_by_name.get(name.casefold(), ()))
    return frozenset(asset.id for index in held for asset in episodes[index])
