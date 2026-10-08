"""Who owns each account's library, and who in one account is who in another.

The registry holds the answers (`people.owner`, `people.companion`); this module reads what an
Immich account says on demand, so the page can offer a name to pick and the owner it can guess
for a second account. Nothing here copies another account's people into the registry: a person
is only linked when somebody picks them.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from immich_memories.config_loader import Config
from immich_memories.config_models import PRIMARY_ACCOUNT
from immich_memories.db import Store
from immich_memories.people.account_ids import entry_ids, ids_by_account
from immich_memories.people.companion import (
    declined_aliases,
    load_document,
    people_entries,
    set_owner,
)
from immich_memories.people.owner import OWNERS
from immich_memories.web.dependencies import current_config
from immich_memories.web.roster import people_store
from immich_memories.web.schemas import AccountPerson

router = APIRouter(prefix="/api/v1", tags=["people"])


@dataclass(frozen=True)
class AccountPersonRecord:
    """One named person as an Immich account holds them."""

    id: str
    name: str
    birth_date: str | None
    pictures: int | None


class AccountReads(Protocol):
    """What the page asks an Immich account, one question at a time and only when it needs to."""

    def people(self, account: str) -> list[AccountPersonRecord]: ...

    def user_name(self, account: str) -> str: ...


# One page opens many cards, each asking for the same account's people; every name costs a
# count call to Immich, so the answer is kept for a minute. Keyed by who is asked, not by a
# name alone, so a settings edit that repoints an account never reads the old server's people.
_PEOPLE_TTL_SECONDS = 60.0
_kept_people: dict[tuple[str, str], tuple[float, list[AccountPersonRecord]]] = {}


class _ImmichAccountReads:
    def __init__(self, config: Config) -> None:
        self._config = config

    def _open(self, account: str) -> Any:
        from immich_memories.api.sync_client import SyncImmichClient
        from immich_memories.web.media_scope import connection_for

        connection = connection_for(self._config.immich, account)
        return SyncImmichClient(
            base_url=connection.url,
            api_key=connection.api_key,
            api_version=self._config.immich.api_version,
        )

    def people(self, account: str) -> list[AccountPersonRecord]:
        from immich_memories.security import credential_fingerprint
        from immich_memories.web.media_scope import connection_for

        connection = connection_for(self._config.immich, account)
        # WHY: a cache key holds a fingerprint, never the key itself, so no debug line
        # or repr of this dict ever prints an account's credential.
        key = (connection.url, credential_fingerprint(connection.api_key))
        kept = _kept_people.get(key)
        if kept is not None and time.monotonic() < kept[0]:
            return kept[1]
        found = self._read_people(account)
        _kept_people[key] = (time.monotonic() + _PEOPLE_TTL_SECONDS, found)
        return found

    def _read_people(self, account: str) -> list[AccountPersonRecord]:
        with self._open(account) as client:
            return [
                AccountPersonRecord(
                    person.id,
                    person.name,
                    person.birth_date.date().isoformat() if person.birth_date else None,
                    _count(client, person.id),
                )
                for person in client.get_all_people()
                if person.name.strip()
            ]

    def user_name(self, account: str) -> str:
        with self._open(account) as client:
            user = client.get_current_user()
        return str(user.name or "")


def _count(client: Any, person_id: str) -> int | None:
    try:
        return int(client.get_person_asset_count(person_id))
    except Exception:  # noqa: BLE001 - a missing count is a blank, not a failed list
        return None


def account_reads(config: Annotated[Config, Depends(current_config)]) -> AccountReads:
    """The reader for this request's configured accounts."""
    return _ImmichAccountReads(config)


class OwnerChoice(BaseModel):
    person_id: str
    name: str


class AccountOwner(BaseModel):
    account: str
    primary: bool
    person_id: str | None
    name: str | None
    # "Nobody in this library": an answer, not a blank.
    nobody: bool
    # confirmed, told, account (the account's own name matched), inferred, or unknown.
    how: str
    choices: list[OwnerChoice]


class OwnerAnswer(BaseModel):
    person_id: str | None


def _known_accounts(config: Config) -> list[str]:
    return [PRIMARY_ACCOUNT, *sorted(config.immich.accounts)]


def _choices(entries: list[dict[str, Any]], account: str) -> list[OwnerChoice]:
    return [
        OwnerChoice(person_id=entry_ids(entry)[0], name=str(entry["name"]))
        for entry in entries
        if entry.get("name") and ids_by_account(entry).get(account)
    ]


def _owner_view(account: str, document: dict[str, Any], reads: AccountReads) -> AccountOwner:
    entries = people_entries(document)
    choices = _choices(entries, account)
    answers = document.get(OWNERS)
    answer = answers.get(account) if isinstance(answers, dict) else None
    person_id: str | None = None
    how = "unknown"
    if isinstance(answer, dict):
        person_id, how = answer.get("person_id"), "confirmed"
    elif account == PRIMARY_ACCOUNT:
        guess = document.get("owner")
        if isinstance(guess, dict):
            person_id = _canonical(entries, guess.get("person_id"))
            how = str(guess.get("identified") or "unknown")
    elif choices:
        person_id = _matching_the_account_user(account, choices, reads)
        how = "account" if person_id else "unknown"
    name = next((c.name for c in choices if c.person_id == person_id), None)
    return AccountOwner(
        account=account,
        primary=account == PRIMARY_ACCOUNT,
        person_id=person_id if name else None,
        name=name,
        nobody=isinstance(answer, dict) and answer.get("person_id") is None,
        how=how,
        choices=choices,
    )


def _canonical(entries: list[dict[str, Any]], person_id: object) -> str | None:
    found = next((entry for entry in entries if person_id in entry_ids(entry)), None)
    return entry_ids(found)[0] if found else None


def _matching_the_account_user(
    account: str, choices: list[OwnerChoice], reads: AccountReads
) -> str | None:
    try:
        user = " ".join(reads.user_name(account).casefold().split())
    except Exception:  # noqa: BLE001 - an unreachable account has no guess, not a failed page
        return None
    return next(
        (c.person_id for c in choices if user and " ".join(c.name.casefold().split()) == user),
        None,
    )


@router.get("/roster/owners", response_model=list[AccountOwner])
def owners(
    store: Annotated[Store, Depends(people_store)],
    config: Annotated[Config, Depends(current_config)],
    reads: Annotated[AccountReads, Depends(account_reads)],
) -> list[AccountOwner]:
    """Whose library each account is, and how we know; a second account is asked on demand."""
    document = load_document(store)
    return [_owner_view(account, document, reads) for account in _known_accounts(config)]


@router.put("/roster/owners/{account}", response_model=AccountOwner)
def answer_owner(
    account: str,
    answer: OwnerAnswer,
    store: Annotated[Store, Depends(people_store)],
    config: Annotated[Config, Depends(current_config)],
    reads: Annotated[AccountReads, Depends(account_reads)],
) -> AccountOwner:
    """Say who owns this account's library, or `null` for nobody. A scan never undoes it."""
    if account not in _known_accounts(config):
        raise HTTPException(404, f"No account named {account!r} is configured.")
    try:
        set_owner(store, answer.person_id, account=account)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return _owner_view(account, load_document(store), reads)


@router.get("/accounts/{name}/people", response_model=list[AccountPerson])
def account_people(
    name: str,
    store: Annotated[Store, Depends(people_store)],
    config: Annotated[Config, Depends(current_config)],
    reads: Annotated[AccountReads, Depends(account_reads)],
    for_person: str | None = None,
) -> list[AccountPerson]:
    """The named people of one account, with their picture counts (`/people/{id}/face` is
    their face).

    With `for_person`, the ones with that person's name (any case) or birth date come first,
    and anybody already declined as "not the same person" is left out.
    """
    if name not in _known_accounts(config):
        raise HTTPException(404, f"No account named {name!r} is configured.")
    document = load_document(store)
    entries = people_entries(document)
    wanted = next((e for e in entries if for_person in entry_ids(e)), None) if for_person else None
    declined = (
        declined_aliases(document).get(entry_ids(wanted)[0], {}).get(name, []) if wanted else []
    )
    holders = _holders_for(entries, name, config)
    found = [
        (
            _match(wanted, person)
            if wanted is not None and person.id not in holders
            else _NO_MATCH,
            AccountPerson(
                id=person.id,
                name=person.name,
                birth_date=person.birth_date,
                pictures=person.pictures,
                suggested=False,
                linked_to=holders.get(person.id),
            ),
        )
        for person in reads.people(name)
        if person.id not in declined
    ]
    ordered = sorted(
        found,
        key=lambda ranked: (
            ranked[0],
            ranked[1].linked_to is not None,
            -(ranked[1].pictures or 0),
            ranked[1].name.casefold(),
        ),
    )
    return [person.model_copy(update={"suggested": rank < _NO_MATCH}) for rank, person in ordered]


def _holders_for(entries: list[dict[str, Any]], account: str, config: Config) -> dict[str, str]:
    from immich_memories.web.media_scope import connection_for

    accounts = {account}
    if config.immich.native_sharing:
        origin = connection_for(config.immich, account).url.rstrip("/")
        accounts.update(
            name
            for name in _known_accounts(config)
            if connection_for(config.immich, name).url.rstrip("/") == origin
        )
    # An ID returned by this account proves access to that server's identity. This
    # is a view only: revoking a share must never leave a new permanent binding.
    return {
        alias: entry_ids(entry)[0]
        for entry in entries
        for name, aliases in ids_by_account(entry).items()
        if name in accounts
        for alias in aliases
    }


_NO_MATCH = 2


def _match(entry: dict[str, Any], person: AccountPersonRecord) -> int:
    """0 for the same name (any case), 1 for the same birth date, else no match."""
    name = " ".join(str(entry.get("name") or "").casefold().split())
    born = entry.get("birth_date")
    if name and name == " ".join(person.name.casefold().split()):
        return 0
    return 1 if born and person.birth_date and str(born) == person.birth_date else _NO_MATCH
