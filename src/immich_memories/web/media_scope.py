"""Which configured account, if any, may answer a media request for one id.

`access_clients.py` already knows a picture's owning account once a pipeline run has
read it, but the web routes serve an id with no run behind it: a browser just asks for
`/assets/{id}/thumbnail`. So before any cache read or Immich fetch, this module asks:
does any account the server is configured with (the primary, or a name under
`immich.accounts`) actually see this id? An id none of them can read is scoped out and
served to nobody, regardless of whether it happens to already sit in the shared cache.

A single-account install has only one account to ask, so it stays the free, no-network
check it always implicitly was. A multi-account install asks Immich once per id, in
account order, and keeps the answer (including "none of them") for the life of the
process; a config reload installs a new `ImmichConfig` object, so its id naturally
starts the cache over rather than serving a stale answer against accounts that moved.
"""

from __future__ import annotations

from collections.abc import Callable
from threading import Lock
from typing import TYPE_CHECKING

from immich_memories.config_models import PRIMARY_ACCOUNT, ImmichConfig, ImmichConnection

if TYPE_CHECKING:
    from immich_memories.api.sync_client import SyncImmichClient

_lock = Lock()
_asset_accounts: dict[tuple[int, str], str | None] = {}
_person_accounts: dict[tuple[int, str], str | None] = {}


def connection_for(immich: ImmichConfig, account: str) -> ImmichConnection:
    """Where `account` reads from: the primary's own fields, or a name under `accounts`."""
    return immich if account == PRIMARY_ACCOUNT else immich.accounts[account]


def _candidates(immich: ImmichConfig) -> tuple[str, ...]:
    return (PRIMARY_ACCOUNT, *sorted(immich.accounts))


def _owner(immich: ImmichConfig, read: Callable[[SyncImmichClient], object]) -> str | None:
    from immich_memories.api.sync_client import SyncImmichClient

    for name in _candidates(immich):
        connection = connection_for(immich, name)
        if not connection.url or not connection.api_key:
            continue
        try:
            with SyncImmichClient(base_url=connection.url, api_key=connection.api_key) as client:
                read(client)
        except Exception:  # noqa: BLE001 - this account cannot serve it; try the next one
            continue
        return name
    return None


def account_for_asset(immich: ImmichConfig, asset_id: str) -> str | None:
    """The configured account that can read this asset id, or None if none can."""
    if not immich.accounts:
        return PRIMARY_ACCOUNT
    key = (id(immich), asset_id)
    with _lock:
        if key in _asset_accounts:
            return _asset_accounts[key]
    account = _owner(immich, lambda client: client.get_asset(asset_id))
    with _lock:
        _asset_accounts[key] = account
    return account


def account_for_person(immich: ImmichConfig, person_id: str) -> str | None:
    """The configured account that can read this person id, or None if none can."""
    if not immich.accounts:
        return PRIMARY_ACCOUNT
    key = (id(immich), person_id)
    with _lock:
        if key in _person_accounts:
            return _person_accounts[key]
    account = _owner(immich, lambda client: client.get_person(person_id))
    with _lock:
        _person_accounts[key] = account
    return account
