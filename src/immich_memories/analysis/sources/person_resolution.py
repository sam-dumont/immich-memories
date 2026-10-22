"""Which faces a named person is, read from the people store before the roster (#1500).

A person in the store answers to every id bound to them, each one under the account that
can read it: the primary account's cluster and a partner account's cluster of the same
person are one person. A run only uses the aliases of the accounts it reads, and a
household run holds each alias to its own account's pictures. A name the store does not
hold falls back to the Immich roster, exactly as before the store existed.

A leaf shaped like a UUID (or a store `manual:` id) is an id, never a name: it picks exactly
the store person with that id or alias, or else the Immich face with that id. A name that
several store people carry picks all of them, and says so (``ResolvedPeople.merged``).

Native evidence may verify requested IDs on the selected connections; saved bindings are never rewritten.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any

from immich_memories.api.native_sharing import NativePeople
from immich_memories.api.person_expression import PersonExpression
from immich_memories.config.models.resources import PRIMARY_ACCOUNT
from immich_memories.people.account_ids import entry_ids, ids_by_account
from immich_memories.people.companion import people_entries

# Manual people exist only in the store; no Immich picture carries their id.
_MANUAL_PREFIX = "manual:"
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


class UnknownPersonId(ValueError):
    """An id-shaped leaf that neither the store nor the Immich roster holds."""


@dataclass(frozen=True)
class PersonAlias:
    """One face identity and the account declaring access to it."""

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
    face_accounts: Mapping[str, str | frozenset[str]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    merged: tuple[tuple[str, tuple[StorePerson, ...]], ...] = ()


def is_person_id(leaf: str) -> bool:
    """Whether a `--person` value is an id (UUID-shaped, or a store `manual:` id)."""
    return bool(_UUID.fullmatch(leaf)) or leaf.startswith(_MANUAL_PREFIX)


def store_people(document: Mapping[str, Any]) -> tuple[StorePerson, ...]:
    """The registry document's people, each with the Immich aliases it binds."""
    found = []
    for entry in people_entries(dict(document)):
        own = entry_ids(entry)
        if not own:
            continue
        aliases = tuple(
            PersonAlias(face, account)
            for account, faces in ids_by_account(entry).items()
            for face in faces
            if not face.startswith(_MANUAL_PREFIX)
        )
        found.append(StorePerson(own[0], str(entry.get("name") or ""), aliases))
    return tuple(found)


@dataclass(frozen=True)
class FollowedFaces:
    """The store's people with every face the roster no longer holds taken off them.

    ``followed`` pairs each re-linked person with the face their name led to; ``lost``
    holds the people left with no face on the account and nobody to stand in for them.
    """

    people: tuple[StorePerson, ...]
    followed: tuple[tuple[StorePerson, str], ...] = ()
    lost: tuple[StorePerson, ...] = ()


def follow_vanished_faces(
    store: Sequence[StorePerson],
    roster: Mapping[str, str],
    account: str = PRIMARY_ACCOUNT,
) -> FollowedFaces:
    """Take `account`'s faces that its roster (face id -> name) no longer holds off the store.

    Immich people belong to one user, so one human is a face in each account that has
    pictures of them, and merging those records in Immich keeps one id and deletes the rest.
    A store person bound to a deleted face would find nothing. Left with no live face on
    `account`, they follow their name to the one roster person carrying it,
    case-insensitively. When another store person of that name already holds that face,
    that record answers for them both, as a shared name always has, until the next scan
    folds the two together (`people.split_people`). Anything less certain is ``lost``, for
    the caller to refuse rather than guess.
    """
    live = {face.casefold() for face in roster}
    holders = {
        alias.face_id.casefold(): person
        for person in store
        for alias in person.aliases
        if alias.face_id.casefold() in live
    }
    by_name: dict[str, list[str]] = {}
    for face, name in roster.items():
        if name.strip():
            by_name.setdefault(name.strip().casefold(), []).append(face)
    people: list[StorePerson] = []
    followed: list[tuple[StorePerson, str]] = []
    lost: list[StorePerson] = []
    for person in store:
        kept = tuple(
            alias
            for alias in person.aliases
            if alias.account != account or alias.face_id.casefold() in live
        )
        if kept == person.aliases or any(alias.account == account for alias in kept):
            people.append(person if kept == person.aliases else replace(person, aliases=kept))
            continue
        name = person.name.strip().casefold()
        named = by_name.get(name, [])
        holder = holders.get(named[0].casefold()) if len(named) == 1 else None
        if len(named) == 1 and holder is None:
            healed = replace(person, aliases=(PersonAlias(named[0], account), *kept))
            holders[named[0].casefold()] = healed
            people.append(healed)
            followed.append((healed, named[0]))
            continue
        people.append(replace(person, aliases=kept))
        if holder is None or holder.name.strip().casefold() != name:
            lost.append(person)
    return FollowedFaces(tuple(people), tuple(followed), tuple(lost))


def resolve_people(
    expression: PersonExpression,
    store: Sequence[StorePerson],
    roster: Callable[[str], PersonExpression],
    *,
    accounts: Sequence[str] = (),
    roster_ids: Callable[[], Collection[str]] = frozenset,
    native: NativePeople | None = None,
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
    leaves = _Leaves(store, roster, roster_ids, frozenset(accounts or (PRIMARY_ACCOUNT,)), native)
    condition = expression.map_leaves(leaves.resolve)
    held = leaves.held if accounts or native else {}
    return ResolvedPeople(condition, MappingProxyType(held), tuple(leaves.merged))


@dataclass
class _Leaves:
    """One resolution's leaves, and what they learned on the way."""

    store: Sequence[StorePerson]
    roster: Callable[[str], PersonExpression]
    roster_ids: Callable[[], Collection[str]]
    readable: frozenset[str]
    native: NativePeople | None = None
    held: dict[str, str | frozenset[str]] = field(default_factory=dict)
    merged: list[tuple[str, tuple[StorePerson, ...]]] = field(default_factory=list)

    def resolve(self, leaf: str) -> PersonExpression:
        matched = _store_matches(self.store, leaf)
        if not any(person.aliases for person in matched):
            if matched and is_person_id(leaf):
                raise ValueError(f"{leaf!r} has no Immich face to find in pictures")
            return self._outside_store(leaf)
        if len(matched) > 1:
            self.merged.append((leaf, tuple(matched)))
        aliases = [alias for person in matched for alias in person.aliases if self._can_read(alias)]
        if not aliases:
            raise ValueError(f"{leaf!r} has no face in the accounts this run reads")
        if self.native:
            for alias in aliases:
                self.native.accounts_for(alias.face_id, alias.account)
            self.native.require_complete([alias.face_id for alias in aliases])
        self.held.update(
            {
                alias.face_id: self.native.accounts_for(alias.face_id, alias.account)
                if self.native
                else alias.account
                for alias in aliases
            }
        )
        faces = tuple(dict.fromkeys(alias.face_id for alias in aliases))
        leaves = tuple(PersonExpression("person", value=face) for face in faces)
        return leaves[0] if len(leaves) == 1 else PersonExpression("any", children=leaves)

    def _can_read(self, alias: PersonAlias) -> bool:
        return alias.account in self.readable or bool(
            self.native and self.native.accounts_for(alias.face_id, alias.account)
        )

    def _outside_store(self, leaf: str) -> PersonExpression:
        if is_person_id(leaf):
            face = leaf.lower()
            if face not in {known.lower() for known in self.roster_ids()}:
                raise UnknownPersonId(leaf)
            condition = PersonExpression("person", value=face)
        else:
            condition = self.roster(leaf)
        if self.native:
            self.native.require_complete(condition.leaf_values)
        self.held.update(
            {
                face: self.native.scopes.get(face, PRIMARY_ACCOUNT)
                if self.native
                else PRIMARY_ACCOUNT
                for face in condition.leaf_values
            }
        )
        return condition


def _store_matches(store: Sequence[StorePerson], leaf: str) -> list[StorePerson]:
    """The store person an id names, else every person carrying the leaf as a name.

    Two people sharing a name are both meant, as two Immich clusters with one name always
    were: the store never merges them, but asking by the name asks for either.
    """
    wanted = leaf.casefold()
    by_id = [
        person
        for person in store
        if person.person_id.casefold() == wanted
        or any(alias.face_id.casefold() == wanted for alias in person.aliases)
    ][:1]
    if is_person_id(leaf):
        return by_id
    named = [person for person in store if person.name and person.name.casefold() == wanted]
    # An id `people show` lists names one person whatever its shape: Immich's ids are UUIDs,
    # but a store id is whatever the registry holds, and the CLI tells users to pass it.
    return named or by_id
