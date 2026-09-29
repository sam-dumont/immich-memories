"""Which faces a `generate` run's people are (#1500).

`--person` and `--people-expression` resolve through the people store
first (`analysis/person_resolution.py`) and fall back to the Immich roster for anybody
the store does not hold, so a run without a people store matches exactly as before.
"""

from __future__ import annotations

import functools
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

import click

from immich_memories.analysis.editorial_source import resolve_named_expression
from immich_memories.analysis.person_presence import people_condition as flat_condition
from immich_memories.analysis.person_resolution import (
    ResolvedPeople,
    StorePerson,
    UnknownPersonId,
    resolve_people,
    store_people,
)
from immich_memories.api.person_expression import PersonExpression
from immich_memories.cli._helpers import print_error, print_success, print_warning
from immich_memories.people.companion import load_document

if TYPE_CHECKING:
    from immich_memories.api.models import Person
    from immich_memories.api.sync_client import SyncImmichClient
    from immich_memories.db import Store


@dataclass(frozen=True)
class RunPeople:
    """The run's people as discovery asks for them: flat face ids, or one condition."""

    person_ids: list[str] = field(default_factory=list)
    condition: PersonExpression | None = None
    face_accounts: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))


def resolve_run_people(
    client: SyncImmichClient,
    *,
    expression: PersonExpression | None,
    person_names: Sequence[str],
    person_match: str,
    accounts: Sequence[str],
    store: Store | None = None,
) -> RunPeople:
    """Resolve `--people-expression` or `--person` names to the faces they mean.

    Names the store holds become every alias the run's accounts can read. Anybody else
    is matched on the primary's roster exactly as before: exact names for an expression,
    the first case-insensitive match for `--person`, which exits when there is none. A
    `--person` run whose every name is one face keeps the flat id list it always used.
    """
    if expression is None and not person_names:
        return RunPeople()
    held = store_people(load_document(store))
    # Read only when somebody falls back to it: a store that knows everybody asks nothing.
    roster = functools.cache(lambda: client.get_all_people(with_hidden=True))
    try:
        if expression is not None:
            resolved = resolve_people(
                expression,
                held,
                lambda name: resolve_named_expression(
                    PersonExpression("person", value=name), roster()
                ),
                accounts=accounts,
                roster_ids=lambda: {person.id for person in roster()},
            )
            _warn_merged(resolved)
            return RunPeople(condition=resolved.condition, face_accounts=resolved.face_accounts)
        return _flat_people(client, held, person_names, person_match, accounts, roster)
    except UnknownPersonId as error:
        raise click.UsageError(
            f"No person with id {error} in the people store or the Immich library"
        ) from None


def _flat_people(
    client: SyncImmichClient,
    held: Sequence[StorePerson],
    person_names: Sequence[str],
    person_match: str,
    accounts: Sequence[str],
    roster: Callable[[], Sequence[Person]],
) -> RunPeople:
    match: Literal["and", "or"] = "or" if person_match == "or" else "and"
    named = flat_condition(person_names, match, None)
    assert named is not None
    from_roster: set[str] = set()

    def roster_match(name: str) -> PersonExpression:
        from_roster.add(name)
        return _first_named(client, name)

    resolved = resolve_people(
        named,
        held,
        roster_match,
        accounts=accounts,
        roster_ids=lambda: {person.id for person in roster()},
    )
    _warn_merged(resolved)
    for name in dict.fromkeys(person_names):
        if name not in from_roster:
            print_success(f"Found person: {name}")
    # One part per distinct name: the name's own face, or an OR over its aliases.
    parts = (resolved.condition,) if named.kind == "person" else resolved.condition.children
    if all(part.kind == "person" and part.value for part in parts):
        ids = [str(part.value) for part in parts]
        return RunPeople(person_ids=ids, face_accounts=resolved.face_accounts)
    return RunPeople(condition=resolved.condition, face_accounts=resolved.face_accounts)


def _warn_merged(resolved: ResolvedPeople) -> None:
    """Say which store people one name picked, and how to pick one of them instead."""
    for leaf, people in resolved.merged:
        lines = [f"{leaf!r} is {len(people)} people in the people store; the film looks for all:"]
        lines += [f"  {person.name} (id {person.person_id}; {_faces(person)})" for person in people]
        lines.append("Use --person <id> to choose one.")
        print_warning("\n".join(lines))


def _faces(person: StorePerson) -> str:
    by_account: dict[str, list[str]] = {}
    for alias in person.aliases:
        by_account.setdefault(alias.account, []).append(alias.face_id)
    return "; ".join(f"{account}: {', '.join(faces)}" for account, faces in by_account.items())


def _first_named(client: SyncImmichClient, name: str) -> PersonExpression:
    found = client.get_person_by_name(name)
    if found is None:
        print_error(f"Person not found: {name}")
        sys.exit(1)
    print_success(f"Found person: {found.name}")
    return PersonExpression("person", value=found.id)
