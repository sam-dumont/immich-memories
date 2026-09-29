"""Who is in a picture, for a film about people: whoever is recognised in its episode.

Immich answers "is this person here" per frame, and a face goes unrecognised for people
who are really there: the back of a head, a baby feeding against a chest, a child across
the garden. So a person counts as present in every picture of an episode (the 90-minute
grouping every film is cut from) where their face is recognised at least once, and in no
picture outside it.

The rule is read once, by the fetch (`api/person_scope.py`), over the window Immich
returns. The pool the owner reviews is that answer, and the cut keeps it: an evidence
exclusion removes a picture for its own reason, never the presence of its neighbours.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
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
    """The run's people (names or IDs) as one condition, or None when it names nobody."""
    if expression is not None:
        return expression
    leaves = tuple(PersonExpression("person", value=value) for value in dict.fromkeys(people))
    if not leaves:
        return None
    if len(leaves) == 1:
        return leaves[0]
    return PersonExpression("all" if person_match == "and" else "any", children=leaves)


def episodes_of(assets: Sequence[Asset]) -> tuple[tuple[Asset, ...], ...]:
    """The canonical episodes of these pictures (``EPISODE_WINDOW_MINUTES``, time and place)."""
    return group_by_time_and_place(assets, window_minutes=EPISODE_WINDOW_MINUTES)


def present_in_episodes(
    episodes: Iterable[Sequence[Asset]],
    condition: PersonExpression,
    *,
    face_accounts: Mapping[str, str] | None = None,
) -> frozenset[str]:
    """Every picture whose episode satisfies ``condition``, whose leaves are face IDs.

    A leaf holds in an episode when that face is recognised on any of its pictures, so
    ``all`` asks for every named person somewhere in the episode, not in one frame. In a
    household run the episode holds every chosen account's copies, and ``face_accounts``
    holds each face to the pictures its own account owns (the first of
    ``access_accounts``): one person found in either account's copy is in the episode.
    """
    episodes = tuple(episodes)
    held = face_accounts or {}
    held_by_face: dict[str, set[int]] = {}
    for index, episode in enumerate(episodes):
        for asset in episode:
            for person in asset.people:
                if _counts_on(asset, person.id, held):
                    held_by_face.setdefault(person.id, set()).add(index)
    holding = condition.evaluate(lambda face: held_by_face.get(face, ()))
    return frozenset(asset.id for index in holding for asset in episodes[index])


def _counts_on(asset: Asset, face: str, held: Mapping[str, str]) -> bool:
    """A face held to an account counts only on the pictures that account owns."""
    return face not in held or held[face] == next(iter(asset.access_accounts), None)
