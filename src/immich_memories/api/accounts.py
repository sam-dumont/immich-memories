"""Open the Immich accounts a run selects, each one checked against `/users/me` first.

The primary account (`immich.url` / `immich.api_key`) is selected as `primary`; extra
accounts by their name under `immich.accounts`. Nothing is opened that was not selected:
configuring a second account never adds its library to a film.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import httpx

from immich_memories.api.compatibility import ResolvedApiVersion, UnsupportedImmichVersion
from immich_memories.api.immich import ImmichAPIError, ImmichAuthError
from immich_memories.api.models import UserInfo
from immich_memories.api.sync_client import SyncImmichClient
from immich_memories.config_models import PRIMARY_ACCOUNT, ImmichConfig, ImmichConnection
from immich_memories.security import sanitize_error_message


class AccountUnavailable(RuntimeError):
    """A selected account is unknown, unreachable, or refused its key. The message names it."""


@dataclass(frozen=True)
class OpenAccount:
    """A verified client for one account; the caller closes `client`."""

    name: str
    client: SyncImmichClient
    user: UserInfo
    api_version: ResolvedApiVersion


def _connection(immich: ImmichConfig, name: str) -> ImmichConnection:
    if name == PRIMARY_ACCOUNT:
        return immich
    if name in immich.accounts:
        return immich.accounts[name]
    known = ", ".join([PRIMARY_ACCOUNT, *sorted(immich.accounts)])
    raise AccountUnavailable(f"Immich account {name!r} is not configured (configured: {known})")


def _open(name: str, connection: ImmichConnection) -> OpenAccount:
    if not connection.url or not connection.api_key:
        raise AccountUnavailable(f"Immich account {name!r} needs both a url and an api_key")
    client = SyncImmichClient(
        base_url=connection.url, api_key=connection.api_key, api_version=connection.api_version
    )
    try:
        version = client.get_api_version()
        user = client.get_current_user()
    except (ImmichAPIError, UnsupportedImmichVersion, httpx.HTTPError, OSError) as error:
        client.close()
        reason = "rejected its API key" if isinstance(error, ImmichAuthError) else "failed"
        detail = sanitize_error_message(str(error)).replace(connection.api_key, "***")
        raise AccountUnavailable(f"Immich account {name!r} {reason}: {detail}") from None
    return OpenAccount(name=name, client=client, user=user, api_version=version)


def open_accounts(immich: ImmichConfig, selected: Iterable[str]) -> dict[str, OpenAccount]:
    """One verified client per selected account name, in selection order.

    Every name is resolved before any request, so an unknown name fails without touching
    the network. Each client is proven with `/users/me`; on the first account that cannot
    be opened, the ones already open are closed and `AccountUnavailable` names the account.
    Error text never holds an API key.
    """
    wanted = {name: _connection(immich, name) for name in dict.fromkeys(selected)}
    opened: dict[str, OpenAccount] = {}
    try:
        for name, connection in wanted.items():
            opened[name] = _open(name, connection)
    except AccountUnavailable:
        for account in opened.values():
            account.client.close()
        raise
    return opened
