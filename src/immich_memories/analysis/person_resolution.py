"""Which faces a named person is, read from the people store before the roster (#1500).

A person in the store answers to every id bound to them, each one under the account that
can read it: the primary account's cluster and a partner account's cluster of the same
person are one person. A run only uses the aliases of the accounts it reads, and a
household run holds each alias to its own account's pictures. A name the store does not
hold falls back to the Immich roster, exactly as before the store existed.

A leaf shaped like a UUID (or a store `manual:` id) is an id, never a name: it picks exactly
the store person with that id or alias, or else the Immich face with that id. A name that
several store people carry picks all of them, and says so (``ResolvedPeople.merged``).

Everything here is pure: the store document and the roster are read before selection.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from immich_memories.api.person_expression import PersonExpression
from immich_memories.config_models import PRIMARY_ACCOUNT

# Manual people exist only in the store; no Immich picture carries their id.
_MANUAL_PREFIX = "manual:"
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


class UnknownPersonId(ValueError):
    """An id-shaped leaf that neither the store nor the Immich roster holds."""


@dataclass(frozen=True)
class PersonAlias:
    """One face cluster of a person, and the account whose pictures carry it."""

    face_id: str
    account: str


@dataclass(frozen=True)
class StorePerson:
    """A store entry as selection sees it: its id, its name and the face clusters bound to it."""

    person_id: str
    name: str
    aliases: tuple[PersonAlias, ...]


@dataclass(frozen=True)
class ResolvedPeople:
    """A people condition over face ids, and the account each face is held to.

    ``face_accounts`` is empty outside a household run: a one-account run matches a face
    on any picture it reads, as it always has. ``merged`` names each leaf that several
    store people answered, with those people.
    """

    condition: PersonExpression
    face_accounts: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    merged: tuple[tuple[str, tuple[StorePerson, ...]], ...] = ()


def is_person_id(leaf: str) -> bool:
    """Whether a `--person` value is an id (UUID-shaped, or a store `manual:` id)."""
    return bool(_UUID.fullmatch(leaf)) or leaf.startswith(_MANUAL_PREFIX)


def store_people(document: Mapping[str, Any]) -> tuple[StorePerson, ...]:
    """The registry document's people, each with the Immich aliases it binds."""
    people = document.get("people")
    if not isinstance(people, list):
        return ()
    found = []
    for entry in people:
        if not isinstance(entry, dict) or not isinstance(entry.get("ids"), list):
            continue
        if not entry["ids"]:
            continue
        accounts = entry.get("accounts") or {}
        aliases = tuple(
            PersonAlias(str(face), accounts.get(face) or PRIMARY_ACCOUNT)
            for face in entry["ids"]
            if not str(face).startswith(_MANUAL_PREFIX)
        )
        found.append(StorePerson(str(entry["ids"][0]), str(entry.get("name") or ""), aliases))
    return tuple(found)


def resolve_people(
    expression: PersonExpression,
    store: Sequence[StorePerson],
    roster: Callable[[str], PersonExpression],
    *,
    accounts: Sequence[str] = (),
    roster_ids: Callable[[], Collection[str]] = frozenset,
) -> ResolvedPeople:
    """Map each leaf (a name, or an id) to the faces it means.

    A leaf the store knows becomes an OR over that person's aliases in the accounts the
    run reads (``accounts``; empty is the primary alone). A name no store person carries
    goes to ``roster``, the Immich-name match a run used before the store, whose faces are
    the primary account's; so does a person the store holds with no Immich face at all.
    An id the store does not hold is a plain face id when ``roster_ids`` holds it, and
    raises ``UnknownPersonId`` otherwise. Raises ``ValueError`` for a store person with no
    alias the run can read: a missing binding is never permission to match another
    account by name.
    """
    leaves = _Leaves(store, roster, roster_ids, frozenset(accounts or (PRIMARY_ACCOUNT,)))
    condition = expression.map_leaves(leaves.resolve)
    held = leaves.held if accounts else {}
    return ResolvedPeople(condition, MappingProxyType(held), tuple(leaves.merged))


@dataclass
class _Leaves:
    """One resolution's leaves, and what they learned on the way."""

    store: Sequence[StorePerson]
    roster: Callable[[str], PersonExpression]
    roster_ids: Callable[[], Collection[str]]
    readable: frozenset[str]
    held: dict[str, str] = field(default_factory=dict)
    merged: list[tuple[str, tuple[StorePerson, ...]]] = field(default_factory=list)

    def resolve(self, leaf: str) -> PersonExpression:
        matched = _store_matches(self.store, leaf)
        if not any(person.aliases for person in matched):
            if matched and is_person_id(leaf):
                raise ValueError(f"{leaf!r} has no Immich face to find in pictures")
            return self._outside_store(leaf)
        if len(matched) > 1:
            self.merged.append((leaf, tuple(matched)))
        aliases = [
            alias
            for person in matched
            for alias in person.aliases
            if alias.account in self.readable
        ]
        if not aliases:
            raise ValueError(f"{leaf!r} has no face in the accounts this run reads")
        self.held.update((alias.face_id, alias.account) for alias in aliases)
        faces = tuple(dict.fromkeys(alias.face_id for alias in aliases))
        leaves = tuple(PersonExpression("person", value=face) for face in faces)
        return leaves[0] if len(leaves) == 1 else PersonExpression("any", children=leaves)

    def _outside_store(self, leaf: str) -> PersonExpression:
        if is_person_id(leaf):
            face = leaf.lower()
            if face not in {known.lower() for known in self.roster_ids()}:
                raise UnknownPersonId(leaf)
            condition = PersonExpression("person", value=face)
        else:
            condition = self.roster(leaf)
        self.held.update(dict.fromkeys(condition.leaf_values, PRIMARY_ACCOUNT))
        return condition


def _store_matches(store: Sequence[StorePerson], leaf: str) -> list[StorePerson]:
    """The store person an id names, else every person carrying the leaf as a name.

    Two people sharing a name are both meant, as two Immich clusters with one name always
    were: the store never merges them, but asking by the name asks for either.
    """
    if is_person_id(leaf):
        wanted_id = leaf.casefold()
        return [
            person
            for person in store
            if person.person_id.casefold() == wanted_id
            or any(alias.face_id.casefold() == wanted_id for alias in person.aliases)
        ][:1]
    wanted = leaf.casefold()
    return [person for person in store if person.name and person.name.casefold() == wanted]
