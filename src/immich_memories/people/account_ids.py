"""A person's ids as the registry document writes them: one list, or one list per account.

A flat `ids: [...]` is the primary account's. A person whose ids come from a second Immich
account writes `ids: {primary: [...], <account>: [...]}` instead, primary first, then the
other accounts by name. The owner declares that mapping (#703's model): nothing here
guesses that two ids are one person.

The person's own id (the store's person id, what links and saved references name) is the
first id listed, unless `person_id` says otherwise. It only has to say so when the id the
person entered the registry with is not the first one the ordering puts out, such as a
partner-account person who later gets a primary id: identity never follows list order.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from itertools import chain
from typing import Any

from immich_memories.config_models import PRIMARY_ACCOUNT

PERSON_ID = "person_id"


def ids_by_account(entry: Mapping[str, Any]) -> dict[str, list[str]]:
    """Each account's ids for one entry, in its written order; a flat list is all primary."""
    ids = entry.get("ids")
    if isinstance(ids, Mapping):
        return {str(account): [str(i) for i in held] for account, held in ids.items()}
    return {PRIMARY_ACCOUNT: [str(i) for i in ids or []]}


def entry_ids(entry: Mapping[str, Any]) -> list[str]:
    """Every id the entry answers to, the person's own id first, then as written."""
    written = list(chain.from_iterable(ids_by_account(entry).values()))
    own = entry.get(PERSON_ID)
    if own is None or own not in written:
        return written
    return [own, *(person_id for person_id in written if person_id != own)]


def primary_ids(entry: Mapping[str, Any]) -> list[str]:
    """The ids the primary account reads."""
    return ids_by_account(entry).get(PRIMARY_ACCOUNT, [])


def ids_value(groups: Mapping[str, list[str]]) -> list[str] | dict[str, list[str]]:
    """The `ids` value for these groups: a flat list when only the primary account holds any."""
    held = {account: ids.copy() for account, ids in groups.items() if ids}
    if set(held) <= {PRIMARY_ACCOUNT}:
        return held.get(PRIMARY_ACCOUNT, [])
    order = sorted(held, key=lambda account: (account != PRIMARY_ACCOUNT, account))
    return {account: held[account] for account in order}


def place_ids(
    entry: MutableMapping[str, Any], groups: Mapping[str, list[str]], own: str | None
) -> None:
    """Write `groups` as the entry's ids, keeping `own` as the person's id whatever the order.

    `own` None makes the first id listed the person's own.
    """
    entry["ids"] = ids_value(groups)
    entry.pop(PERSON_ID, None)
    if own is not None and next(chain.from_iterable(ids_by_account(entry).values())) != own:
        entry[PERSON_ID] = own
