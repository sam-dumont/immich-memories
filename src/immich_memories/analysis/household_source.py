"""Read a film's window from every Immich account the run chose (#1500).

Each chosen account is opened and proven with `/users/me`, then asked for the same window
through the same full-context fetch a one-account run uses. Every picture keeps the
accounts that can open it, and the run's client learns to read it through its owner's. Partner sharing shows one account another's pictures, so only
pictures the chosen accounts themselves own are kept: sharing never pulls a third
library into the film. A read that fails fails the run, naming the account.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import httpx

from immich_memories.analysis.editorial_source import FullEditorialSource
from immich_memories.analysis.selection_source import SourceScope, _with_access_accounts
from immich_memories.analysis.source_filter import asset_of
from immich_memories.api.access_clients import AccessBoundClient
from immich_memories.api.accounts import AccountUnavailable, OpenAccount
from immich_memories.api.immich import ImmichAPIError
from immich_memories.api.models import Asset, VideoClipInfo
from immich_memories.security import sanitize_error_message

Source = Asset | VideoClipInfo
WindowFetch = Callable[[FullEditorialSource, SourceScope], Sequence[Source]]


def fetch_household_source(
    client: AccessBoundClient, accounts: Sequence[str], scope: SourceScope, fetch: WindowFetch
) -> tuple[Source, ...]:
    """Every chosen account's pictures in the scope, each tagged with who can open it.

    The same asset read by two accounts comes back once per read; selection coalesces
    them into one picture. The accounts stay open on `client`, which from here reads each
    picture through its owner's account. Raises `AccountUnavailable` naming the first
    account that cannot be opened or read, so a household never passes for complete with
    one missing.
    """
    opened = client.open_accounts(accounts)
    owners = {account.user.id: name for name, account in opened.items()}
    sources: list[Source] = []
    for name, account in opened.items():
        sources.extend(
            # The owner's account can always open its own picture, so it leads even
            # on a read that came through a partner: the preference rides in every
            # tag, not in the order the accounts were read.
            _with_access_accounts(source, (owners[asset_of(source).owner_id], name))
            for source in _read(name, account, scope, fetch)
            if asset_of(source).owner_id in owners
        )
    client.routes.learn(asset_of(source) for source in sources)
    return tuple(sources)


def _read(
    name: str, account: OpenAccount, scope: SourceScope, fetch: WindowFetch
) -> Sequence[Source]:
    try:
        return fetch(account.client, scope)
    except (ImmichAPIError, httpx.HTTPError, OSError) as error:
        detail = sanitize_error_message(str(error))
        raise AccountUnavailable(f"Immich account {name!r} could not be read: {detail}") from None
