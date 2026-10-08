"""Which configured account, if any, may answer a media request for one id.

`access_clients.py` already knows a picture's owning account once a pipeline run has
read it, but the web routes serve an id with no run behind it: a browser just asks for
`/assets/{id}/thumbnail`. So before any cache read or Immich fetch, this module asks:
does any account the server is configured with (the primary, or a name under
`immich.accounts`) actually see this id? An id none of them can read is scoped out and
served to nobody, regardless of whether it happens to already sit in the shared cache.

A single-account install has only one account to ask, so it stays the free, no-network
check it always implicitly was. A multi-account install asks Immich once per id, in
account order, and keeps the answer for a while: a positive stays long enough that a
revoke or a newly shared picture still converges within the process's life, and a
negative stays only briefly, so one account outage does not read as a permanent 404.
The cache key folds in every candidate's own url and key, not just the `ImmichConfig`
object's identity: a settings edit or reload builds a new object, and a renamed or
removed account must never let an old entry hand a stale name to `connection_for`.
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from collections.abc import Callable
from threading import Lock
from typing import TYPE_CHECKING

from immich_memories.config_models import PRIMARY_ACCOUNT, ImmichConfig, ImmichConnection
from immich_memories.security import credential_fingerprint

if TYPE_CHECKING:
    from immich_memories.api.sync_client import SyncImmichClient

# A positive answer outlives most sessions, so sharing or revoking access still reaches
# every request within one coffee break; a negative is short so one account's timeout or
# 5xx cannot read as "nobody can see this" for longer than it takes to ask again.
_POSITIVE_TTL_SECONDS = 15 * 60.0
_NEGATIVE_TTL_SECONDS = 60.0
_MAX_ENTRIES = 10_000

# A clean refusal: the account exists and answered, it just does not have this id.
# Anything else (a timeout, a 5xx, a dropped connection) says nothing about ownership.
_DEFINITE_REFUSAL_STATUS = (403, 404)

_Signature = tuple[tuple[str, str, str], ...]

_lock = Lock()
_asset_accounts: OrderedDict[tuple[_Signature, str], tuple[str | None, float]] = OrderedDict()
_person_accounts: OrderedDict[tuple[_Signature, str], tuple[str | None, float]] = OrderedDict()


def connection_for(immich: ImmichConfig, account: str) -> ImmichConnection:
    """Where `account` reads from: the primary's own fields, or a name under `accounts`."""
    return immich if account == PRIMARY_ACCOUNT else immich.accounts[account]


def _candidates(immich: ImmichConfig) -> tuple[str, ...]:
    return (PRIMARY_ACCOUNT, *sorted(immich.accounts))


def _signature(immich: ImmichConfig) -> _Signature:
    """The exact accounts a probe would run against: a changed url, key, name or roster
    is a different signature, so an entry a reload or settings edit left behind can only
    ever miss, never hand a since-renamed or removed account name back to a caller.

    Keys enter as fingerprints, never raw: a signature tuple repr'd in a debug line or
    a crash state must not print an account's credential."""
    return tuple(
        (
            name,
            connection_for(immich, name).url,
            credential_fingerprint(connection_for(immich, name).api_key),
        )
        for name in _candidates(immich)
    )


def account_set_signature(immich: ImmichConfig) -> str:
    """One digest over the whole account set: any changed url, key, name or roster
    turns it over. Web thumbnail filenames include it, so a picture can never be
    served under accounts its bytes were not fetched for."""
    digest = hashlib.sha256()
    for name, url, fingerprint in _signature(immich):
        digest.update(f"{len(name)}:{name}{len(url)}:{url}{fingerprint}".encode())
    return digest.hexdigest()


def _probe_one(
    immich: ImmichConfig, name: str, read: Callable[[SyncImmichClient], object]
) -> bool | None:
    """True if `name` reads it, False if it cleanly refuses, None if the attempt itself
    failed and so proves nothing about who owns it."""
    from immich_memories.api.immich import ImmichAPIError
    from immich_memories.api.sync_client import SyncImmichClient

    connection = connection_for(immich, name)
    if not connection.url or not connection.api_key:
        return False
    try:
        with SyncImmichClient(base_url=connection.url, api_key=connection.api_key) as client:
            read(client)
    except ImmichAPIError as error:
        return False if error.status_code in _DEFINITE_REFUSAL_STATUS else None
    except Exception:  # noqa: BLE001 - an unreachable account proves nothing either way
        return None
    return True


def _owner(
    immich: ImmichConfig, read: Callable[[SyncImmichClient], object]
) -> tuple[str | None, bool]:
    """The account that owns it (or None), and whether that answer may be cached at all.

    A clean "no" from every configured account is worth remembering; an outage along the
    way is not, so the next request gets a fresh chance rather than a frozen miss.
    """
    every_refusal_was_clean = True
    for name in _candidates(immich):
        verdict = _probe_one(immich, name, read)
        if verdict is True:
            return name, True
        if verdict is None:
            every_refusal_was_clean = False
    return None, every_refusal_was_clean


def _recall(
    cache: OrderedDict[tuple[_Signature, str], tuple[str | None, float]],
    key: tuple[_Signature, str],
) -> tuple[bool, str | None]:
    with _lock:
        entry = cache.get(key)
        if entry is None:
            return False, None
        account, expires_at = entry
        if time.monotonic() >= expires_at:
            del cache[key]
            return False, None
        cache.move_to_end(key)
        return True, account


def _remember(
    cache: OrderedDict[tuple[_Signature, str], tuple[str | None, float]],
    key: tuple[_Signature, str],
    account: str | None,
    ttl_seconds: float,
) -> None:
    with _lock:
        cache[key] = (account, time.monotonic() + ttl_seconds)
        cache.move_to_end(key)
        while len(cache) > _MAX_ENTRIES:
            cache.popitem(last=False)


def _resolve(
    cache: OrderedDict[tuple[_Signature, str], tuple[str | None, float]],
    immich: ImmichConfig,
    item_id: str,
    read: Callable[[SyncImmichClient], object],
) -> str | None:
    key = (_signature(immich), item_id)
    hit, cached = _recall(cache, key)
    if hit:
        return cached
    account, cacheable = _owner(immich, read)
    if account is not None:
        _remember(cache, key, account, _POSITIVE_TTL_SECONDS)
    elif cacheable:
        _remember(cache, key, None, _NEGATIVE_TTL_SECONDS)
    return account


def account_for_asset(immich: ImmichConfig, asset_id: str) -> str | None:
    """The configured account that can read this asset id, or None if none can."""
    if not immich.accounts:
        return PRIMARY_ACCOUNT
    return _resolve(_asset_accounts, immich, asset_id, lambda client: client.get_asset(asset_id))


def account_for_person(immich: ImmichConfig, person_id: str) -> str | None:
    """The configured account that can read this person id, or None if none can."""
    if not immich.accounts:
        return PRIMARY_ACCOUNT
    return _resolve(
        _person_accounts, immich, person_id, lambda client: client.get_person(person_id)
    )
