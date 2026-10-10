"""One completed source boundary between discovery and every kind of film.

Discovery chooses pictures and, optionally, a wider context for reading their events.
Companion videos support those pictures; they never become independent candidates.
The editor receives this snapshot and cannot rediscover a different pool.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from immich_memories.analysis.editorial_source import FullEditorialSource, fetch_full_window_source
from immich_memories.analysis.household_source import (
    fetch_household_source,
    primary_owned_only,
    source_accounts,
)
from immich_memories.analysis.selection_source import SourceScope, _coalesce_sources
from immich_memories.analysis.source_filter import asset_of
from immich_memories.analysis.special_event_scope import select_source_members
from immich_memories.api.access_clients import AccessBoundClient
from immich_memories.api.immich import ImmichAPIError
from immich_memories.api.models import Asset, VideoClipInfo

logger = logging.getLogger(__name__)
Source = Asset | VideoClipInfo


class CompanionSource(Protocol):
    """Read a linked video through the account that supplied its photograph."""

    def get_asset(self, asset_id: str) -> Asset: ...


@dataclass(frozen=True)
class EditorialSourcePool:
    """Selectable pictures, context-only pictures, and their supporting video files."""

    selectable: tuple[Source, ...]
    context: tuple[Source, ...] = ()
    companions: tuple[Asset, ...] = ()

    @property
    def sources(self) -> tuple[Source, ...]:
        """The full evidence snapshot; membership remains in ``selectable``."""
        return (*self.selectable, *self.context, *self.companions)


def resolve_source_pool(
    client: CompanionSource,
    selected: Sequence[Source],
    *,
    context: Sequence[Source] | None = None,
) -> EditorialSourcePool:
    """Complete every source route identically, without widening selectable membership.

    Reuse captured companions, resolve missing ones once, and retain owner routes on them.
    Only a confirmed 404 becomes unavailable motion; transport or account failures stop the run.
    """
    if context is None:
        sources, _ = _coalesce_sources(selected)
    else:
        # Context discovery already enforced owner and event boundaries. A stale
        # initial selection must not put a refused picture back into the source.
        admitted = {asset_of(source).id for source in context}
        sources, _ = _coalesce_sources(
            (*context, *(source for source in selected if asset_of(source).id in admitted))
        )
    by_id = {asset_of(source).id: source for source in sources}
    photos = [
        asset for asset in map(asset_of, sources) if asset.is_live_photo and not asset.is_video
    ]
    linked = {asset.live_photo_video_id for asset in photos}
    requested = dict.fromkeys(asset_of(source).id for source in selected)
    return EditorialSourcePool(
        selectable=tuple(by_id[key] for key in requested if key in by_id and key not in linked),
        context=tuple(
            source for source in sources if asset_of(source).id not in requested.keys() | linked
        ),
        companions=_resolve_companions(client, sources, photos),
    )


def _resolve_companions(
    client: CompanionSource, sources: Sequence[Source], photos: Sequence[Asset]
) -> tuple[Asset, ...]:
    """Preserve known video metadata and distinguish absent media from failed reads."""
    by_id = {asset_of(source).id: source for source in sources}
    if isinstance(client, AccessBoundClient):
        client.routes.learn(asset_of(source) for source in sources)
    companions: dict[str, Asset | None] = {}
    for photo in photos:
        video_id = photo.live_photo_video_id
        assert video_id is not None
        if video_id in companions:
            continue
        try:
            companion = (
                asset_of(by_id[video_id]) if video_id in by_id else client.get_asset(video_id)
            )
        except ImmichAPIError as error:
            if error.status_code != 404:
                raise
            companions[video_id] = None
            continue
        if companion.id != video_id or not companion.is_video:
            raise ValueError("Live Photo companion metadata disagrees with its source link")
        companions[video_id] = companion.model_copy(
            update={"access_accounts": companion.access_accounts or photo.access_accounts}
        )
    missing = sum(companion is None for companion in companions.values())
    if missing:
        logger.warning(
            "%d Live Photo companion(s) are unavailable in Immich; their pictures remain stills",
            missing,
        )
    return tuple(companion for companion in companions.values() if companion is not None)


def discover_source_context(
    client: FullEditorialSource,
    scope: SourceScope,
    *,
    accounts: Sequence[str] = (),
) -> tuple[Source, ...]:
    """Read the explicitly requested contextual windows before entering the editor."""
    owners = source_accounts(client, accounts)
    if owners:
        if not isinstance(client, AccessBoundClient):
            raise TypeError("a run that names accounts reads through an AccessBoundClient")
        sources = fetch_household_source(client, owners, scope, fetch_full_window_source)
    else:
        sources = primary_owned_only(client, fetch_full_window_source(client, scope))
    return select_source_members(sources, scope.asset_ids)
