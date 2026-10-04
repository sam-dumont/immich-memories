"""Which pictures and faces `--ask`'s chosen accounts can see (#2044, #1500, #2013).

A household run shares one store across several Immich accounts, but the store itself
names no account (`annotation_assets` has no owner column): every picture a producer ever
wrote is one row, however many libraries fed it. A one-account run has always been safe
because the store then held exactly one library -- but once any account other than the
primary has ever read into it (`--accounts`, or native sharing), it does not. Without this,
`--ask` built its pool, verdict, trace and rule preview from every account's pictures, even
on a request naming none.

This reads each chosen account's own library fresh from Immich, over the span the store's
pictures cover, and keeps the ownership the household fetch already enforces for a dated
run (`analysis/household_source.py`): partner sharing shows one account another's
pictures, but only pictures an account owns travel under its name.
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
from immich_memories.api.native_sharing import NativePeople
from immich_memories.api.sync_client import SyncImmichClient
from immich_memories.config_models import PRIMARY_ACCOUNT
from immich_memories.db import Store
from immich_memories.free_text.library import LibraryPicture
from immich_memories.people.companion import load_document
from immich_memories.store.editorial_preparation import household_seen, single_account_confirmed
from immich_memories.timeperiod import DateRange

# The store's capture time and Immich's taken filter can sit in different time zones.
_MARGIN = timedelta(days=1)

_EMPTY_STR: Mapping[str, str] = MappingProxyType({})
_EMPTY_FACE: Mapping[str, str | frozenset[str]] = MappingProxyType({})


@dataclass(frozen=True)
class AccountScope:
    """What the asking accounts can see: who owns each picture, and who owns each face.

    Empty outside a household run: a one-account run reads every picture in the store, as
    it always has.
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


def likely_household(store: Store, *, other_accounts: bool, native_sharing: bool) -> bool:
    """Whether this store might hold more than the primary's own pictures.

    True when the config names another account or turns on native sharing; or, sticky,
    once `store_meta` has ever recorded a non-primary access account
    (`store/editorial_preparation.py::household_seen`) -- which outlives the partner being
    dropped from config, native sharing being turned off, or a restore that carries the
    marker with it, since `annotation_assets` itself has no owner column to tell an old
    household picture apart from the primary's own; or, cheaply, when the people registry
    already holds an alias under another account, evidence of the same thing for a store
    written before this marker existed.

    A legacy store with none of these signals yet is not assumed single-account either:
    only a real ownership-aware read that actually confirmed every asset it saw was the
    primary's (`single_account_confirmed`) turns this False, so an install upgrading into
    this code pays the safe, scoped read at most until its next ordinary run earns that.
    """
    if other_accounts or native_sharing or household_seen(store):
        return True
    if any(
        alias.account != PRIMARY_ACCOUNT
        for person in store_people(load_document(store))
        for alias in person.aliases
    ):
        return True
    return not single_account_confirmed(store)


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
    native = client.native_people(accounts)
    return AccountScope(
        picture_accounts=MappingProxyType(picture_accounts),
        face_accounts=_face_accounts(store, accounts, native),
    )


def _face_accounts(
    store: Store, accounts: Sequence[str], native: NativePeople | None
) -> Mapping[str, str | frozenset[str]]:
    """Each store person's canonical id held to the accounts that can read a face of them.

    `translate()` reads a picture's faces already canonicalised to one id per person
    (`library.read_library`), so unlike the run's own face-by-face resolution
    (`person_resolution.resolve_people`, keyed by the raw Immich id a picture actually
    carries) this has to fold every one of a person's accounts under that single id, or a
    partner-owned picture recognised only through the partner's own cluster would look
    like nobody is in it. `native`, when the config turns on native sharing, verifies a
    saved binding against fresh evidence (`api/native_sharing.py`) the same way a dated
    household run's own face resolution does. A known person held to no readable account
    still gets an entry, frozen empty: `present_on_assets`'s own default, a face missing
    from this mapping entirely, counts it on every picture, which is exactly what a person
    the chosen accounts cannot read must not do.
    """
    readable = frozenset(accounts)
    held: dict[str, str | frozenset[str]] = {}
    for person in store_people(load_document(store)):
        if not person.aliases:
            continue
        owners: set[str] = set()
        for alias in person.aliases:
            if alias.account not in readable:
                continue
            verified = (
                native.accounts_for(alias.face_id, alias.account) if native else (alias.account,)
            )
            owners.update(verified)
        held[person.person_id] = next(iter(owners)) if len(owners) == 1 else frozenset(owners)
    return MappingProxyType(held)
