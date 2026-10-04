"""Who is in a picture, for a film about people: strictly who Immich recognised on it.

A people condition is decided per picture, not per gathering (#1954): a face must be
recognised on that exact asset for the person to count there. Immich still misses faces
that are really present (the back of a head, a baby feeding against a chest, a child
across the garden), but widening a match to the rest of the episode let waterfalls, food
stills and documents with zero recognised people into a film about specific people, which
is worse than the occasional missed picture. Better lose a good picture than bundle in a
wrong one.

The rule is read once, by the fetch (`api/person_scope.py`), over the window Immich
returns. The pool the owner reviews is that answer, and the cut keeps it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

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


def present_on_assets(
    assets: Sequence[Asset],
    condition: PersonExpression,
    *,
    face_accounts: Mapping[str, str | frozenset[str]] | None = None,
) -> frozenset[str]:
    """Every asset whose own recognised faces satisfy ``condition`` (leaves are face IDs).

    ``all`` asks for every named person recognised on that one picture, not spread across
    a gathering; ``any`` asks for at least one of them there. In a household run,
    ``face_accounts`` holds each face to an explicit owner or a verified set of selected
    owners: a face counts only on pictures those owners hold, never on another account's
    copy of the same moment. Download routing still uses the first of ``access_accounts``.
    """
    held = face_accounts or {}
    assets_by_face: dict[str, set[str]] = {}
    for asset in assets:
        for person in asset.people:
            if _counts_on(asset, person.id, held):
                assets_by_face.setdefault(person.id, set()).add(asset.id)
    return condition.evaluate(lambda face: assets_by_face.get(face, ()))


def _counts_on(asset: Asset, face: str, held: Mapping[str, str | frozenset[str]]) -> bool:
    """Count only on the declared owner or verified native owner set."""
    if face not in held:
        return True
    accounts = held[face]
    owner = next(iter(asset.access_accounts), None)
    return owner == accounts if isinstance(accounts, str) else owner in accounts
