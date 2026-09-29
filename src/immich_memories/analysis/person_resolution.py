"""Which faces a named person is, read from the people store before the roster (#1500).

A person in the store answers to every id bound to them, each one under the account that
can read it: the primary account's cluster and a partner account's cluster of the same
person are one person. A run only uses the aliases of the accounts it reads, and a
household run holds each alias to its own account's pictures. A name the store does not
hold falls back to the Immich roster, exactly as before the store existed.

Everything here is pure: the store document and the roster are read before selection.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from immich_memories.api.person_expression import PersonExpression
from immich_memories.config_models import PRIMARY_ACCOUNT

# Manual people exist only in the store; no Immich picture carries their id.
_MANUAL_PREFIX = "manual:"


@dataclass(frozen=True)
class PersonAlias:
    """One face cluster of a person, and the account whose pictures carry it."""

    face_id: str
    account: str


@dataclass(frozen=True)
class StorePerson:
    """A store entry as selection sees it: a name and the face clusters bound to it."""

    name: str
    aliases: tuple[PersonAlias, ...]


@dataclass(frozen=True)
class ResolvedPeople:
    """A people condition over face ids, and the account each face is held to.

    ``face_accounts`` is empty outside a household run: a one-account run matches a face
    on any picture it reads, as it always has.
    """

    condition: PersonExpression
    face_accounts: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))


def store_people(document: Mapping[str, Any]) -> tuple[StorePerson, ...]:
    """The registry document's people, each with the Immich aliases it binds."""
    people = document.get("people")
    if not isinstance(people, list):
        return ()
    found = []
    for entry in people:
        if not isinstance(entry, dict) or not isinstance(entry.get("ids"), list):
            continue
        accounts = entry.get("accounts") or {}
        aliases = tuple(
            PersonAlias(str(face), accounts.get(face) or PRIMARY_ACCOUNT)
            for face in entry["ids"]
            if not str(face).startswith(_MANUAL_PREFIX)
        )
        found.append(StorePerson(str(entry.get("name") or ""), aliases))
    return tuple(found)


def resolve_people(
    expression: PersonExpression,
    store: Sequence[StorePerson],
    roster: Callable[[str], PersonExpression],
    *,
    accounts: Sequence[str] = (),
) -> ResolvedPeople:
    """Map each leaf (a name, or any id a store person holds) to the faces it means.

    A leaf the store knows becomes an OR over that person's aliases in the accounts the
    run reads (``accounts``; empty is the primary alone). A leaf it does not know goes to
    ``roster``, the Immich-name match a run used before the store, whose faces are the
    primary account's; so does a person the store holds with no Immich face at all. Raises ``ValueError`` for a store person with no alias the run can
    read: a missing binding is never permission to match another account by name.
    """
    readable = frozenset(accounts) or {PRIMARY_ACCOUNT}
    held: dict[str, str] = {}

    def resolve(leaf: str) -> PersonExpression:
        matched = _store_matches(store, leaf)
        if not any(person.aliases for person in matched):
            condition = roster(leaf)
            held.update(dict.fromkeys(condition.leaf_values, PRIMARY_ACCOUNT))
            return condition
        aliases = [
            alias for person in matched for alias in person.aliases if alias.account in readable
        ]
        if not aliases:
            raise ValueError(f"{leaf!r} has no face in the accounts this run reads")
        held.update((alias.face_id, alias.account) for alias in aliases)
        faces = tuple(dict.fromkeys(alias.face_id for alias in aliases))
        leaves = tuple(PersonExpression("person", value=face) for face in faces)
        return leaves[0] if len(leaves) == 1 else PersonExpression("any", children=leaves)

    condition = expression.map_leaves(resolve)
    return ResolvedPeople(condition, MappingProxyType(held if accounts else {}))


def _store_matches(store: Sequence[StorePerson], leaf: str) -> list[StorePerson]:
    """The store person holding ``leaf`` as an id, else every person carrying it as a name.

    Two people sharing a name are both meant, as two Immich clusters with one name always
    were: the store never merges them, but asking by the name asks for either.
    """
    by_id = [person for person in store if any(a.face_id == leaf for a in person.aliases)]
    if by_id:
        return by_id
    wanted = leaf.casefold()
    return [person for person in store if person.name and person.name.casefold() == wanted]
