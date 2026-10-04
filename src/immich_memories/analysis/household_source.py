"""Read a film's window from every Immich account the run chose (#1500).

Each chosen account is opened and proven with `/users/me`, then asked for the same window
through the same full-context fetch a one-account run uses. Every picture keeps the
accounts that can open it, and the run's client learns to read it through its owner's.
Partner sharing shows one account another's pictures, so only pictures the chosen accounts
themselves own are kept: sharing never pulls a third library into the film. A read that
fails fails the run, naming the account.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import httpx

from immich_memories.analysis.editorial_source import FullEditorialSource
from immich_memories.analysis.selection_source import (
    SourceScope,
    _coalesce_sources,
    _with_access_accounts,
)
from immich_memories.analysis.source_filter import asset_of
from immich_memories.api.access_clients import AccessBoundClient
from immich_memories.api.accounts import AccountUnavailable
from immich_memories.api.immich import ImmichAPIError
from immich_memories.api.models import Asset, VideoClipInfo
from immich_memories.api.sync_client import SyncImmichClient
from immich_memories.config_models import PRIMARY_ACCOUNT
from immich_memories.security import sanitize_error_message
from immich_memories.timeperiod import DateRange

Source = Asset | VideoClipInfo
WindowFetch = Callable[[FullEditorialSource, SourceScope], Sequence[Source]]


def source_accounts(client: FullEditorialSource, accounts: Sequence[str]) -> tuple[str, ...]:
    """Keep native identity reads inside the selected owners, even for primary alone."""
    if isinstance(client, AccessBoundClient) and client.uses_native_identities:
        return tuple(accounts) or (PRIMARY_ACCOUNT,)
    return tuple(accounts)


def fetch_household_source(
    client: AccessBoundClient, accounts: Sequence[str], scope: SourceScope, fetch: WindowFetch
) -> tuple[Source, ...]:
    """Every chosen account's pictures in the scope, each tagged with who can open it.

    Repeated reads of one asset are coalesced before discovery deduplicates windows,
    keeping every owner's favourite and face evidence. The accounts stay open on `client`, which from here reads each
    picture through its owner's account. Raises `AccountUnavailable` naming the first
    account that cannot be opened or read, so a household never passes for complete with
    one missing.
    """
    return tuple(HouseholdWindows(client, accounts).each(lambda account: fetch(account, scope)))


class HouseholdWindows:
    """Every chosen account's read of a window, as one window source.

    Person presence reads the household through this (`api/person_scope.py`): one episode
    holds both accounts' copies, so a face recognised on either copy puts its person there.
    The accounts are the run client's, opened once and kept open until it closes.
    """

    def __init__(self, client: AccessBoundClient, accounts: Sequence[str]) -> None:
        self._client = client
        self._opened = client.open_accounts(accounts)
        self._owners = {
            (account.client.base_url, account.user.id): name
            for name, account in self._opened.items()
        }
        self._origins: dict[str, str] = {}

    def each(self, read: Callable[[SyncImmichClient], Sequence[Source]]) -> list[Source]:
        """``read`` asked of every chosen account, each picture tagged with who can open it."""
        sources: list[Source] = []
        for name, account in self._opened.items():
            for source in _read(name, read, account.client):
                asset = asset_of(source)
                origin = account.client.base_url
                owner = self._owners.get((origin, asset.owner_id))
                if owner is None:
                    continue
                self._check_origin(asset, origin)
                # The owner's key leads even when this read came through a partner.
                sources.append(_with_access_accounts(source, (owner, name)))
        self._client.routes.learn(asset_of(source) for source in sources)
        # Discovery also reads this source before editorial selection. Fold repeated IDs
        # here so its first-arrival dedup cannot discard the owner's star or faces.
        return list(_coalesce_sources(sources)[0])

    def _check_origin(self, asset: Asset, origin: str) -> None:
        for identity in (asset.id, asset.live_photo_video_id):
            if identity and self._origins.setdefault(identity, origin) != origin:
                raise AccountUnavailable(
                    "The same asset ID occurs on different Immich servers; use separate runs "
                    "so originals and Live Photo companions cannot be routed to the wrong owner."
                )

    def get_videos_for_date_range(self, date_range: DateRange) -> list:
        """Every chosen account's videos in the window."""
        return self.each(lambda client: client.get_videos_for_date_range(date_range))

    def get_photos_for_date_range(
        self,
        date_range: DateRange,
        progress_callback: Callable[[int, int], None] | None = None,
        person_id: str | None = None,
        person_ids: list[str] | None = None,
    ) -> list:
        """Every chosen account's photos in the window."""
        return self.each(
            lambda client: client.get_photos_for_date_range(
                date_range, progress_callback, person_id=person_id, person_ids=person_ids
            )
        )


def _read(
    name: str, read: Callable[[SyncImmichClient], Sequence[Source]], client: SyncImmichClient
) -> Sequence[Source]:
    try:
        return read(client)
    except (ImmichAPIError, httpx.HTTPError, OSError) as error:
        detail = sanitize_error_message(str(error))
        raise AccountUnavailable(f"Immich account {name!r} could not be read: {detail}") from None
