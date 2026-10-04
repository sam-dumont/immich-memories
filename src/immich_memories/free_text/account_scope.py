"""Which pictures and faces `--ask`'s chosen accounts can see (#2044, #1500, #2013).

A household run shares one store across several Immich accounts, but the store itself
names no account (`annotation_assets` has no owner column): every picture a producer ever
wrote is one row, however many libraries fed it. A one-account run has always been safe
because the store then holds exactly one library. A household run is not: without this,
`--ask` built its pool, verdict, trace and rule preview from every account's pictures.

This reads each chosen account's own library fresh from Immich, over the span the store's
pictures cover, and keeps the ownership the household fetch already enforces for a dated
run (`analysis/household_source.py`): partner sharing shows one account another's
pictures, but only pictures an account owns travel under its name. A one-account run names
no accounts and is untouched.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from types import MappingProxyType

from immich_memories.analysis.household_source import HouseholdWindows
from immich_memories.analysis.person_resolution import store_people
from immich_memories.analysis.source_filter import asset_of
from immich_memories.api.access_clients import AccessBoundClient
from immich_memories.api.sync_client import SyncImmichClient
from immich_memories.db import Store
from immich_memories.free_text.library import LibraryPicture
from immich_memories.people.companion import load_document
from immich_memories.timeperiod import DateRange

# The store's capture time and Immich's taken filter can sit in different time zones.
_MARGIN = timedelta(days=1)

_EMPTY_STR: Mapping[str, str] = MappingProxyType({})
_EMPTY_FACE: Mapping[str, str | frozenset[str]] = MappingProxyType({})


@dataclass(frozen=True)
class AccountScope:
    """What the asking accounts can see: who owns each picture, and who owns each face.

    Empty outside a household run (`--accounts` names more than the primary alone): a
    one-account run reads every picture in the store, as it always has.
    """

    picture_accounts: Mapping[str, str] = _EMPTY_STR
    face_accounts: Mapping[str, str | frozenset[str]] = _EMPTY_FACE


def visible_pictures(
    pictures: Sequence[LibraryPicture], scope: AccountScope
) -> tuple[LibraryPicture, ...]:
    """`pictures` the asking accounts can see; every picture when `scope` names none."""
    if not scope.picture_accounts:
        return tuple(pictures)
    return tuple(p for p in pictures if p.asset_id in scope.picture_accounts)


def resolve_account_scope(
    client: SyncImmichClient,
    accounts: Sequence[str],
    pictures: Sequence[LibraryPicture],
    store: Store,
) -> AccountScope:
    """The pictures and faces `accounts` can see, read fresh from Immich.

    A one-account run (`accounts` empty) makes no request and returns the empty scope: the
    pool, trace and preview read the whole store, exactly as before this existed.
    """
    if not accounts or not pictures:
        return AccountScope()
    if not isinstance(client, AccessBoundClient):
        raise TypeError("a request naming accounts reads through an AccessBoundClient")
    window = DateRange(
        start=min(picture.taken_at for picture in pictures) - _MARGIN,
        end=max(picture.taken_at for picture in pictures) + _MARGIN,
    )
    windows = HouseholdWindows(client, accounts)
    sources = [
        *windows.get_photos_for_date_range(window),
        *windows.get_videos_for_date_range(window),
    ]
    picture_accounts: dict[str, str] = {}
    for source in sources:
        asset = asset_of(source)
        if not asset.access_accounts:
            continue
        owner = asset.access_accounts[0]
        picture_accounts[asset.id] = owner
        if asset.live_photo_video_id:
            picture_accounts.setdefault(asset.live_photo_video_id, owner)
    return AccountScope(
        picture_accounts=MappingProxyType(picture_accounts),
        face_accounts=_face_accounts(store, accounts),
    )


def _face_accounts(store: Store, accounts: Sequence[str]) -> Mapping[str, str | frozenset[str]]:
    readable = frozenset(accounts)
    held: dict[str, str | frozenset[str]] = {}
    for person in store_people(load_document(store)):
        owners = {alias.account for alias in person.aliases if alias.account in readable}
        if owners:
            held[person.person_id] = next(iter(owners)) if len(owners) == 1 else frozenset(owners)
    return MappingProxyType(held)
