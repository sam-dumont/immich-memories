"""Which faces a `generate` run's people are (#1500).

`--person` and `--people-expression` resolve through the people store
first (`analysis/person_resolution.py`) and fall back to the Immich roster for anybody
the store does not hold, so a run without a people store matches exactly as before.
"""

from __future__ import annotations

import functools
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

from immich_memories.analysis.editorial_source import resolve_named_expression
from immich_memories.analysis.person_presence import people_condition as flat_condition
from immich_memories.analysis.person_resolution import resolve_people, store_people
from immich_memories.api.person_expression import PersonExpression
from immich_memories.cli._helpers import print_error, print_success
from immich_memories.people.companion import load_document

if TYPE_CHECKING:
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
    if expression is not None:
        # Read only when somebody falls back to it: a store that knows everybody asks nothing.
        roster = functools.cache(lambda: client.get_all_people(with_hidden=True))
        resolved = resolve_people(
            expression,
            held,
            lambda name: resolve_named_expression(PersonExpression("person", value=name), roster()),
            accounts=accounts,
        )
        return RunPeople(condition=resolved.condition, face_accounts=resolved.face_accounts)
    match: Literal["and", "or"] = "or" if person_match == "or" else "and"
    named = flat_condition(person_names, match, None)
    assert named is not None
    from_roster: set[str] = set()

    def roster_match(name: str) -> PersonExpression:
        from_roster.add(name)
        return _first_named(client, name)

    resolved = resolve_people(named, held, roster_match, accounts=accounts)
    for name in dict.fromkeys(person_names):
        if name not in from_roster:
            print_success(f"Found person: {name} (people store)")
    # One part per distinct name: the name's own face, or an OR over its aliases.
    parts = (resolved.condition,) if named.kind == "person" else resolved.condition.children
    if all(part.kind == "person" and part.value for part in parts):
        ids = [str(part.value) for part in parts]
        return RunPeople(person_ids=ids, face_accounts=resolved.face_accounts)
    return RunPeople(condition=resolved.condition, face_accounts=resolved.face_accounts)


def _first_named(client: SyncImmichClient, name: str) -> PersonExpression:
    found = client.get_person_by_name(name)
    if found is None:
        print_error(f"Person not found: {name}")
        sys.exit(1)
    print_success(f"Found person: {found.name}")
    return PersonExpression("person", value=found.id)
