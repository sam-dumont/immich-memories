"""Read each picture through the account that can open it (#1500).

A household run reads several Immich accounts, and a partner's own picture may be one the
primary key cannot download. So every read of a picture (its details, faces, preview,
original, Live Photo motion and playback) goes through the account its source read named
first: its owner's. Uploads, searches and everything else stay on the primary account.
A picture no account named, which is every picture of a one-account run, is read through
the primary exactly as it always has been.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from threading import Lock
from typing import TypeVar

import httpx

from immich_memories.api import sync_client
from immich_memories.api.accounts import AccountUnavailable, OpenAccount, open_accounts
from immich_memories.api.compatibility import ApiVersionPolicy
from immich_memories.api.immich import ImmichAPIError
from immich_memories.api.models import Asset, AssetFace
from immich_memories.api.sync_client import SyncImmichClient
from immich_memories.config_models import PRIMARY_ACCOUNT, ImmichConfig
from immich_memories.security import sanitize_error_message

_Read = TypeVar("_Read")


# WHY not a RuntimeError: a render drops one clip it cannot decode and goes on, but a
# household read that fails means the film would silently lose an owner's picture, or
# be tempted to play another account's copy. It has to stop the attempt.
class AccountReadFailed(Exception):
    """The account that owns a picture could not read it. The message names the account."""


class AccessRoutes:
    """Which account reads each asset id; one table shared by a run's clients and threads."""

    def __init__(self) -> None:
        self._accounts: dict[str, str] = {}
        self._lock = Lock()

    def learn(self, assets: Iterable[Asset]) -> None:
        """Route each asset, and its Live Photo motion half, to the first account that read it."""
        with self._lock:
            for asset in assets:
                if not asset.access_accounts:
                    continue
                account = asset.access_accounts[0]
                self._accounts[asset.id] = account
                if asset.live_photo_video_id:
                    self._accounts.setdefault(asset.live_photo_video_id, account)

    def account_of(self, asset_id: str) -> str | None:
        with self._lock:
            return self._accounts.get(asset_id)


class AccessBoundClient(SyncImmichClient):
    """The run's client: the primary account's, reading each routed picture through its account.

    Accounts are opened once, proven with `/users/me`, and kept until this client closes, so
    selection, preview and render share them. One instance belongs to one thread, like any
    `SyncImmichClient`; `sibling` gives another thread its own connections over the same routes.
    """

    def __init__(
        self,
        immich: ImmichConfig,
        *,
        routes: AccessRoutes | None = None,
        timeout: float = 30.0,
        api_version: ApiVersionPolicy | str | None = None,
    ) -> None:
        super().__init__(
            base_url=immich.url,
            api_key=immich.api_key,
            timeout=timeout,
            api_version=immich.api_version if api_version is None else api_version,
        )
        self._immich = immich
        self._api_version = api_version
        self.routes = routes or AccessRoutes()
        self._accounts: dict[str, OpenAccount] = {}

    def open_accounts(self, names: Sequence[str]) -> dict[str, OpenAccount]:
        """The named accounts, opened on first use and kept open until `close`.

        Raises `AccountUnavailable` naming the first account that cannot be opened.
        """
        missing = [name for name in dict.fromkeys(names) if name not in self._accounts]
        self._accounts.update(open_accounts(self._immich, missing))
        return {name: self._accounts[name] for name in dict.fromkeys(names)}

    def sibling(self) -> AccessBoundClient:
        """A client for another thread: the same routes, its own connections."""
        return AccessBoundClient(
            self._immich, routes=self.routes, timeout=self.timeout, api_version=self._api_version
        )

    def close(self) -> None:
        try:
            for account in self._accounts.values():
                account.client.close()
        finally:
            self._accounts.clear()
            super().close()

    def _routed(self, asset_id: str, read: Callable[[SyncImmichClient], _Read]) -> _Read:
        account = self.routes.account_of(asset_id)
        if account is None:
            return read(self)
        try:
            if account == PRIMARY_ACCOUNT:
                return read(self)
            return read(self.open_accounts([account])[account].client)
        except (ImmichAPIError, AccountUnavailable, httpx.HTTPError, OSError) as error:
            detail = sanitize_error_message(str(error))
            raise AccountReadFailed(
                f"Immich account {account!r} could not read asset {asset_id}: {detail}"
            ) from None

    # Each read calls the base class on whichever client the route picks, so the primary's
    # own reads never come back through this router.
    def get_asset(self, asset_id: str) -> Asset:
        return self._routed(asset_id, lambda client: SyncImmichClient.get_asset(client, asset_id))

    def get_asset_faces(self, asset_id: str) -> list[AssetFace]:
        return self._routed(
            asset_id, lambda client: SyncImmichClient.get_asset_faces(client, asset_id)
        )

    def get_asset_thumbnail(self, asset_id: str, size: str = "preview") -> bytes:
        return self._routed(
            asset_id, lambda client: SyncImmichClient.get_asset_thumbnail(client, asset_id, size)
        )

    def get_video_playback(self, asset_id: str) -> bytes:
        return self._routed(
            asset_id, lambda client: SyncImmichClient.get_video_playback(client, asset_id)
        )

    def download_playback(self, asset_id: str, output_path: Path) -> Path:
        return self._routed(
            asset_id,
            lambda client: SyncImmichClient.download_playback(client, asset_id, output_path),
        )

    def get_video_playback_range(self, asset_id: str, start: int, length: int) -> tuple[bytes, int]:
        return self._routed(
            asset_id,
            lambda client: SyncImmichClient.get_video_playback_range(
                client, asset_id, start, length
            ),
        )

    def download_asset(
        self, asset_id: str, output_path: Path, *, expected_size_bytes: int | None = None
    ) -> Path:
        return self._routed(
            asset_id,
            lambda client: SyncImmichClient.download_asset(
                client, asset_id, output_path, expected_size_bytes=expected_size_bytes
            ),
        )


def reads_for(immich: ImmichConfig, assets: Iterable[Asset]) -> SyncImmichClient:
    """A client for one stage's reads of these assets; the caller closes it.

    Assets no account named (every one-account run) get the plain primary client.
    """
    named = [asset for asset in assets if asset.access_accounts]
    if not named:
        # Looked up at call time, so the plain client stays the one seam it always was.
        return sync_client.SyncImmichClient(
            base_url=immich.url, api_key=immich.api_key, api_version=immich.api_version
        )
    routes = AccessRoutes()
    routes.learn(named)
    return AccessBoundClient(immich, routes=routes)
