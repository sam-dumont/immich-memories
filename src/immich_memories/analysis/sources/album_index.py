"""Which Immich albums hold which assets, read once for a whole run.

An album name is the one name for an occasion that somebody in the family typed.
A reading that may not invent a name still needs somewhere to get one, and this
is it. Membership is indexed album-first: one listing plus one read per album,
whatever the library's size, rather than one lookup per picture.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from immich_memories.security import write_secret_file

logger = logging.getLogger(__name__)

ALBUM_INDEX_NAME = "album-index.private.json"
# Which assets each album held when last read, so a later run reads only changed albums.
ALBUM_MEMBERS_NAME = "album-members.private.json"
_MEMO_SCHEMA = "album-members-v1"

# One read of an album is one `/search/metadata` page, which returns at most a
# thousand assets, so a bigger album would be indexed only in part anyway. It is
# also the size where an album stops naming anything: Immich's own smart albums
# ('Recents', 'Favorites') run to tens of thousands of assets, and
# api/search_service.py already pages them under a limit for the same reason.
MAX_INDEXED_ALBUM_ASSETS = 1_000


@dataclass(frozen=True, slots=True)
class AlbumMembershipIndex:
    """The album names holding each asset, and which albums that came from."""

    names_by_asset: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    indexed_albums: tuple[str, ...] = ()
    skipped_albums: tuple[str, ...] = ()

    def names_for(self, asset_ids: Sequence[str]) -> tuple[str, ...]:
        """Every album holding any of these assets, each named once."""
        found: dict[str, None] = {}
        for asset_id in asset_ids:
            for name in self.names_by_asset.get(asset_id, ()):
                found.setdefault(name, None)
        return tuple(found)

    def as_record(self) -> dict[str, Any]:
        """What the run says about the index it built."""
        return {
            "schema": "album-index-v1",
            "indexed_albums": list(self.indexed_albums),
            "skipped_albums": list(self.skipped_albums),
            "max_album_assets": MAX_INDEXED_ALBUM_ASSETS,
            "assets_held": len(self.names_by_asset),
        }


NO_ALBUMS = AlbumMembershipIndex()


def build_album_index(
    source: object,
    *,
    max_album_assets: int = MAX_INDEXED_ALBUM_ASSETS,
    memo_path: Path | None = None,
) -> AlbumMembershipIndex:
    """Map assets to the albums holding them, skipping albums too big to name anything.

    With `memo_path`, an album whose update stamp and count are what the last run saw is
    answered from that run's read instead of searched again (#2711); only changed or new
    albums cost a request. The memo is the owner's own cache, never shared.
    """
    albums = _listing(source)
    if albums is None:
        return NO_ALBUMS
    remembered = _read_memo(memo_path)
    members: dict[str, tuple[str, ...]] = {}
    names_by_asset: dict[str, list[str]] = {}
    indexed: list[str] = []
    skipped: list[str] = []
    for album in albums:
        if album.asset_count > max_album_assets:
            skipped.append(album.name)
            continue
        assets = _members(source, album, remembered)
        if assets is None:
            skipped.append(album.name)
            continue
        members[album.id] = assets
        indexed.append(album.name)
        for asset_id in assets:
            names_by_asset.setdefault(asset_id, []).append(album.name)
    if memo_path is not None:
        _write_memo(memo_path, albums, members)
    return AlbumMembershipIndex(
        names_by_asset={asset: tuple(names) for asset, names in names_by_asset.items()},
        indexed_albums=tuple(indexed),
        skipped_albums=tuple(skipped),
    )


def _revision(album: Any) -> list[Any] | None:
    """What changes when an album's members do; None when Immich gave no update stamp."""
    updated = getattr(album, "updated_at", None)
    return [updated, album.asset_count] if updated else None


def _members(source: object, album: Any, remembered: Mapping[str, Any]) -> tuple[str, ...] | None:
    entry = remembered.get(album.id)
    revision = _revision(album)
    if revision is not None and isinstance(entry, dict) and entry.get("revision") == revision:
        return tuple(str(asset_id) for asset_id in entry.get("assets", ()))
    assets = _album_assets(source, album.id)
    if assets is None:
        return None
    return tuple(asset_id for asset in assets if (asset_id := str(asset.get("id") or "")))


def _read_memo(path: Path | None) -> Mapping[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.debug("Album memo unreadable (%s); every album is read again", type(exc).__name__)
        return {}
    albums = data.get("albums") if isinstance(data, dict) else None
    return albums if isinstance(albums, dict) and data.get("schema") == _MEMO_SCHEMA else {}


def _write_memo(path: Path, albums: Sequence[Any], members: Mapping[str, tuple[str, ...]]) -> None:
    kept = {
        album.id: {"revision": revision, "assets": list(members[album.id])}
        for album in albums
        if album.id in members and (revision := _revision(album)) is not None
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        write_secret_file(path, json.dumps({"schema": _MEMO_SCHEMA, "albums": kept}))
    except OSError as exc:  # WHY: a memo that cannot be kept only costs the next run a read
        logger.warning("Could not keep the album memo (%s)", type(exc).__name__)


def _listing(source: object) -> Sequence[Any] | None:
    """The library's albums, or None when this source cannot answer for them."""
    list_albums = getattr(source, "list_albums", None)
    if not callable(list_albums) or not callable(getattr(source, "list_album_assets", None)):
        return None
    try:
        return list(list_albums())
    except Exception as exc:  # WHY: no album names reads worse, a failed cut reads nothing
        logger.debug("Album listing unavailable (%s); episodes read without album names", exc)
        return None


def _album_assets(source: object, album_id: str) -> Sequence[Mapping[str, Any]] | None:
    try:
        return list(source.list_album_assets(album_id))  # type: ignore[attr-defined]
    except Exception as exc:  # WHY: one unreadable album must not cost the other names
        logger.debug("Album %s unreadable (%s); its name is not offered", album_id, exc)
        return None


def record_album_index(index: AlbumMembershipIndex, directory: Path) -> None:
    """Say which albums a run could take a name from, beside its episode readings."""
    try:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        write_secret_file(
            directory / ALBUM_INDEX_NAME,
            json.dumps(index.as_record(), ensure_ascii=False, indent=2),
        )
    except Exception as exc:  # Diagnostics cannot change the answer.
        logger.warning("Could not record the album index (%s)", type(exc).__name__)


class RunAlbumNames:
    """One album index per run, built when the first episode asks for a name."""

    def __init__(
        self,
        source: object,
        *,
        record: Callable[[AlbumMembershipIndex], None] | None = None,
        memo_path: Path | None = None,
    ) -> None:
        self._source = source
        self._record = record
        self._memo_path = memo_path
        self._index: AlbumMembershipIndex | None = None

    def __call__(self, asset_ids: Sequence[str]) -> tuple[str, ...]:
        """The album names holding these assets, indexing the library on first use."""
        if self._index is None:
            self._index = build_album_index(self._source, memo_path=self._memo_path)
            if self._record is not None:
                self._record(self._index)
        return self._index.names_for(asset_ids)
