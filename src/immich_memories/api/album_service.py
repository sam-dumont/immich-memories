"""Upload and album management API service."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from immich_memories.api.permissions import ApiKeyCapabilities
    from immich_memories.timeperiod import DateRange

from immich_memories.api.compatibility import ResolvedApiVersion
from immich_memories.api.film_label import FilmLabel
from immich_memories.api.generated_asset_tags import GENERATED_MEMORY_TAG, generated_asset_ids

RequestFn = Callable[..., Any]
ApiVersionFn = Callable[[], Awaitable[ResolvedApiVersion]]

_UPLOAD_MEDIA_TYPES = {
    ".mov": "video/quicktime",
    ".mp4": "video/mp4",
}

# The device identity the V2 upload stamps on its own assets. Read back by the
# cleanup below, so the two must stay the same string. Immich v3 dropped
# deviceId from both the upload form and the asset response, so on v3 only the
# provenance tag says a render is ours.
_UPLOAD_DEVICE_ID = "immich-memories"


logger = logging.getLogger(__name__)

# Immich reads every upload in a background job (exiftool, ffprobe) that ends by
# writing the file's own tag list over the asset's tags, so a tag applied while
# that read runs is wiped (#1270). Only that read gives the exif a modifyDate.
_POLL_SECONDS = 0.5
_READ_WAIT_POLLS = 120
# Immich reads a film once it reaches the front of its metadata queue, and a long film waits
# there behind its own thumbnails and transcode: a 1 GB year film was read after the minute a
# short film needs, and the read took its description back (#2540). The wait grows with the
# file, up to a quarter of an hour.
_READ_WAIT_POLLS_PER_GB = 480
_READ_WAIT_MAX_POLLS = 1800
_TAG_ATTEMPTS = 3
# Reads with the asset unchanged before Immich counts as done rewriting it: each tag or
# description write makes it write the film's sidecar, then read the whole film again (Immich 3's
# ffprobe scans every packet) and write back what it read when that read began. The asset stays
# unchanged while it reads, so the quiet grows with the file: two quiet seconds passed while a
# 1 GB film was still being read, and the late read took its description and tags back (#2540).
_SETTLE_POLLS = 4
_SETTLE_POLLS_PER_GB = 60
_SETTLE_MAX_POLLS = 240
# The key right that lets the app write a film's description.
DESCRIBE = "asset.update"


class InvalidUploadResponse(ValueError):
    """Raised when Immich returns a malformed successful upload response."""


class AlbumNotFoundError(LookupError):
    """Raised when an album reference matches no album name or ID."""


class AmbiguousAlbumError(LookupError):
    """Raised when an album name matches more than one album.

    Immich libraries synced from iOS routinely carry several albums with the
    same name ('Récentes', 'Favorites'), so a name alone is not an identifier.
    """


@dataclass(frozen=True)
class AlbumRef:
    """An album resolved to its ID, display name and asset count.

    ``start`` and ``end`` are when its earliest and latest pictures were taken,
    as Immich reports them; None when Immich did not say. ``updated_at`` is Immich's
    own stamp for the album, which moves when its members do.
    """

    id: str
    name: str
    asset_count: int
    start: datetime | None = None
    end: datetime | None = None
    updated_at: str | None = None


# WHY these two bars are relative, never a fixed size or a list of names: a
# phone's catch-all ("Recents", in whatever language the phone speaks) is 600
# pictures in one library and 38,000 in another, and a trip album in a small
# library can be bigger than a whole year in another. What sets a catch-all
# apart is its proportion to the film. At most `pool` of an album's pictures
# can belong to the film, so an album more than twice the pool's size is
# mostly other films. And an album whose dates run mostly outside the window
# is filed around some other time.
_MAX_ALBUM_TO_POOL = 2.0
_MIN_SPAN_INSIDE_WINDOW = 0.75


@dataclass(frozen=True)
class FilmScope:
    """The window a film covers and how many pictures it drew from.

    ``pool`` is every picture the film could have picked (the period's, or the
    person's within it), not the cut.
    """

    start: datetime
    end: datetime
    pool: int

    def is_curated_for(self, album: AlbumRef) -> bool:
        """Whether this album was made for a film like this one.

        A catch-all holding most of the cut is not the film's name: it holds most
        of every cut. An album counts only when it is not out of proportion to
        the film's pool and its own dates fall mostly inside the film's window.
        A person film over twenty years holds a decade-long catch-all's whole
        span, so there size alone decides.
        """
        if album.asset_count > _MAX_ALBUM_TO_POOL * max(self.pool, 1):
            return False
        if album.start is None or album.end is None:
            return True
        album_start, album_end = _utc(album.start), _utc(album.end)
        span = (album_end - album_start).total_seconds()
        inside = (
            min(album_end, _utc(self.end)) - max(album_start, _utc(self.start))
        ).total_seconds()
        if span <= 0:
            return inside >= 0
        return inside / span >= _MIN_SPAN_INSIDE_WINDOW


def build_upload_fields(
    version: ResolvedApiVersion,
    file_path: Path,
    modified_at: datetime,
    captured_at: datetime | None = None,
) -> dict[str, str]:
    """Build deterministic request fields without opening or reading file contents.

    ``captured_at`` is when the content itself happened, offset included; it is
    what files the asset in the Immich timeline. Without one the file's own
    mtime stands in, which puts the asset on the day it was written.
    V2 identity intentionally retains the legacy hash of the real filename and file size.
    """
    common_fields = {
        "fileCreatedAt": (captured_at or modified_at).isoformat(),
        "fileModifiedAt": modified_at.isoformat(),
    }
    if version is ResolvedApiVersion.V3:
        return {"filename": file_path.name} | common_fields

    file_hash = hashlib.sha256(file_path.name.encode() + str(file_path.stat().st_size).encode())
    identity_fields = {
        "deviceAssetId": f"{_UPLOAD_DEVICE_ID}-{file_hash.hexdigest()[:16]}",
        "deviceId": _UPLOAD_DEVICE_ID,
    }
    return identity_fields | common_fields


def _file_sha1(file_path: Path) -> str:
    with file_path.open("rb") as f:
        return hashlib.file_digest(f, lambda: hashlib.sha1(usedforsecurity=False)).hexdigest()


def _upload_asset_id(data: Any) -> str:
    if not isinstance(data, dict):
        raise InvalidUploadResponse("Upload response must contain a non-empty string id")
    asset_id = data.get("id")
    if not isinstance(asset_id, str) or not asset_id.strip():
        raise InvalidUploadResponse("Upload response must contain a non-empty string id")
    return asset_id


@dataclass(frozen=True)
class UploadWaits:
    """How long to wait on Immich for one upload, in polls: for its first read, and the quiet
    that counts as done rewriting it after each write. Both grow with the file."""

    read_polls: int = _READ_WAIT_POLLS
    quiet_polls: int = _SETTLE_POLLS


def upload_waits(size_bytes: int) -> UploadWaits:
    """The waits an upload of this size gets."""
    gigabytes = max(size_bytes, 0) / 1_000_000_000
    return UploadWaits(
        read_polls=min(
            _READ_WAIT_POLLS + int(_READ_WAIT_POLLS_PER_GB * gigabytes), _READ_WAIT_MAX_POLLS
        ),
        quiet_polls=min(_SETTLE_POLLS + int(_SETTLE_POLLS_PER_GB * gigabytes), _SETTLE_MAX_POLLS),
    )


def _upload_media_type(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    try:
        return _UPLOAD_MEDIA_TYPES[suffix]
    except KeyError as exc:
        raise ValueError(f"Unsupported upload file suffix: {suffix or '<none>'}") from exc


def _utc(moment: datetime) -> datetime:
    # A naive window is the run's own local days; a day either way is noise at
    # the proportions these bars judge.
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


def _album_date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _album_ref(album: dict) -> AlbumRef:
    return AlbumRef(
        id=album["id"],
        name=album.get("albumName") or album["id"],
        asset_count=album.get("assetCount") or 0,
        start=_album_date(album.get("startDate")),
        end=_album_date(album.get("endDate")),
        updated_at=album.get("updatedAt") or None,
    )


def _tag_rights_missing(allows: Callable[[str], bool]) -> list[str]:
    """The tag rights this key lacks to file a film under a tag."""
    return [permission for permission in ("tag.create", "tag.asset") if not allows(permission)]


class AlbumService:
    """Upload and album management operations against the Immich API."""

    def __init__(
        self,
        request_fn: RequestFn,
        api_version_fn: ApiVersionFn,
        key_capabilities_fn: Callable[[], Awaitable[ApiKeyCapabilities]] | None = None,
    ) -> None:
        self._request = request_fn
        self._get_api_version = api_version_fn
        self._get_key_capabilities = key_capabilities_fn

    async def upload_asset(self, file_path: Path, *, captured_at: datetime | None = None) -> str:
        """Upload a file to Immich. Returns the asset ID.

        ``captured_at`` files the asset on the day its content happened; without
        one it lands on the day the file was written.
        """
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        content_type = _upload_media_type(file_path)
        version = await self._get_api_version()
        stat = file_path.stat()
        modified_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
        fields = build_upload_fields(version, file_path, modified_at, captured_at)

        checksum = _file_sha1(file_path)

        with file_path.open("rb") as f:
            data = await self._request(
                "POST",
                "/assets",
                data=fields,
                files={"assetData": (file_path.name, f, content_type)},
                # WHY: Immich answers "duplicate" instead of storing a second copy
                # of a file whose SHA-1 it already holds for this user.
                headers={"x-immich-checksum": checksum},
                timeout=600.0,  # 10 min for large video uploads on slow connections
                before_retry=lambda: self._stored_upload(checksum),
            )
        return _upload_asset_id(data)

    async def _stored_upload(self, checksum: str) -> dict[str, str] | None:
        """The asset a failed attempt stored anyway, so a retry does not store it twice.

        A 5xx or a timeout can arrive after Immich has written the asset. The
        library is asked for the file's checksum first; only a file it does not
        hold (or holds only in the trash) is sent again.
        """
        try:
            data = await self._request(
                "POST",
                "/assets/bulk-upload-check",
                json={"assets": [{"id": "upload", "checksum": checksum}]},
            )
        except Exception:  # WHY: an unanswered check still leaves the checksum header
            logger.debug("Upload check failed; retrying the upload", exc_info=True)
            return None
        results = data.get("results") if isinstance(data, dict) else None
        found = results[0] if isinstance(results, list) and results else {}
        asset_id = found.get("assetId") if isinstance(found, dict) else None
        if not isinstance(asset_id, str) or found.get("isTrashed"):
            return None
        logger.info("An earlier upload attempt already stored this film as %s", asset_id)
        return {"id": asset_id, "status": "duplicate"}

    async def create_album(self, name: str, description: str | None = None) -> str:
        """Create an album in Immich. Returns the album ID.

        A timeout or 5xx can arrive after Immich stored the album; a retry that sent the
        request again made a second one, and every later lookup by name then refused the
        name as ambiguous (#2354). So each retry first looks for the album by name.
        """
        body: dict = {"albumName": name}
        if description:
            body["description"] = description
        data = await self._request(
            "POST", "/albums", json=body, before_retry=lambda: self._stored_album(name)
        )
        return data["id"]

    async def _stored_album(self, name: str) -> dict[str, str] | None:
        try:
            # One look, not a read's own 45 s of backoff inside the write's.
            albums = await self._request("GET", "/albums", retry=False)
        except Exception:  # WHY: an unanswered lookup only means the create is sent again
            logger.debug("Album lookup failed; retrying the create", exc_info=True)
            return None
        found = next(
            (
                album
                for album in (albums if isinstance(albums, list) else [])
                if isinstance(album, dict) and album.get("albumName") == name
            ),
            None,
        )
        return {"id": found["id"]} if found and found.get("id") else None

    async def add_assets_to_album(self, album_id: str, asset_ids: list[str]) -> None:
        await self._request("PUT", f"/albums/{album_id}/assets", json={"ids": asset_ids})

    async def get_albums(self) -> list[dict]:
        return await self._request("GET", "/albums")

    async def albums_containing(self, asset_id: str) -> list[AlbumRef]:
        """Every album holding one asset."""
        data = await self._request("GET", "/albums", params={"assetId": asset_id})
        albums = data if isinstance(data, list) else []
        return [_album_ref(a) for a in albums if isinstance(a, dict) and a.get("id")]

    async def album_holding_most(self, asset_ids: Sequence[str], *, scope: FilmScope) -> str | None:
        """The name of the album this cut mostly sits in, if one was made for it.

        Answers "what did this family day get called" for a title, from a name
        somebody typed rather than anything invented. Only albums curated for a
        film of this ``scope`` take part (see `FilmScope.is_curated_for`): a
        picture that only the phone's catch-all holds is filed nowhere. The bar
        comes from the cut's own composition: the leading album has to hold more
        of the cut than the pictures no such album claims. A day filed across
        two albums still learns the bigger one's name; two pictures out of ten
        learn nothing. Between albums holding as much of the cut as each other,
        the smaller album wins.

        One request per picture of the cut, once per film.
        """
        cut = list(dict.fromkeys(asset_ids))
        held: Counter[str] = Counter()
        refs: dict[str, AlbumRef] = {}
        unfiled = 0
        for asset_id in cut:
            albums = [ref for ref in await self._albums_of(asset_id) if scope.is_curated_for(ref)]
            unfiled += not albums
            for ref in albums:
                held[ref.id] += 1
                refs[ref.id] = ref
        if not held:
            logger.info("No album made for this film holds any of the cut's %d pictures", len(cut))
            return None
        leader = max(held, key=lambda album: (held[album], -refs[album].asset_count))
        logger.info(
            "Leading album holds %d of the cut's %d pictures, %d of which sit in no album "
            "made for this film",
            held[leader],
            len(cut),
            unfiled,
        )
        return refs[leader].name if held[leader] > unfiled else None

    async def _albums_of(self, asset_id: str) -> list[AlbumRef]:
        try:
            return await self.albums_containing(asset_id)
        except Exception:  # WHY: one deleted asset must not cost the whole answer
            logger.debug("Album lookup failed for %s", asset_id, exc_info=True)
            return []

    async def list_albums(self) -> list[AlbumRef]:
        """Albums that could make a memory, largest first.

        Empty albums are dropped: they cannot produce anything, so offering them
        in a picker only invites a dead end.
        """
        albums = await self.get_albums()
        refs = [_album_ref(a) for a in albums if (a.get("assetCount") or 0) > 0]
        refs.sort(key=lambda ref: ref.asset_count, reverse=True)
        return refs

    async def resolve_album(self, name_or_id: str) -> AlbumRef:
        """Resolve an album reference to its ID, name and asset count.

        Matches an album ID first, then an exact name, then a case-insensitive
        name, so users can pass what they see in Immich.

        Raises:
            AmbiguousAlbumError: the name matches several albums.
            AlbumNotFoundError: nothing matches.
        """
        albums = await self.get_albums()

        by_id = {a.get("id"): a for a in albums}
        if name_or_id in by_id:
            return _album_ref(by_id[name_or_id])

        exact = [a for a in albums if a.get("albumName") == name_or_id]
        folded = name_or_id.casefold()
        matches = exact or [a for a in albums if (a.get("albumName") or "").casefold() == folded]

        if len(matches) == 1:
            return _album_ref(matches[0])
        if matches:
            raise AmbiguousAlbumError(
                f"{len(matches)} albums are named {name_or_id!r}. Pass the ID instead:\n"
                + "\n".join(
                    f"  {a['id']}  ({a.get('assetCount') or 0} assets)"
                    for a in sorted(matches, key=lambda a: -(a.get("assetCount") or 0))
                )
            )

        known = ", ".join(sorted({n for a in albums if (n := a.get("albumName"))})) or "none"
        raise AlbumNotFoundError(
            f"No Immich album named or with ID {name_or_id!r}. Albums: {known}"
        )

    async def find_album_by_name(self, name: str) -> str | None:
        """Returns album ID if found, None otherwise."""
        albums = await self.get_albums()
        for album in albums:
            if album.get("albumName") == name:
                return album["id"]
        return None

    async def list_album_assets(self, album_id: str) -> list[dict]:
        """Every asset in an album, via search: /albums/{id} omits them on Immich 3.x.

        Search answers at most 1000 per page, so the pages are followed until
        Immich stops naming a next one.
        """
        assets: list[dict] = []
        page: int | None = 1
        while page:
            data = await self._request(
                "POST",
                "/search/metadata",
                json={"albumIds": [album_id], "size": 1000, "page": page},
            )
            found = (data or {}).get("assets", {})
            assets.extend(found.get("items", []))
            page = int(found["nextPage"]) if found.get("nextPage") else None
        return assets

    async def tag_as_generated(self, asset_id: str) -> None:
        """File one asset under this app's provenance tag, creating the tag if needed.

        The tag is how a later run knows the film is ours on any API version: it
        refuses it as source footage and may replace it with a re-render.
        """
        tags = await self._request("PUT", "/tags", json={"tags": [GENERATED_MEMORY_TAG]})
        tag_id = next(
            tag["id"]
            for tag in tags
            if isinstance(tag, dict) and tag.get("value") == GENERATED_MEMORY_TAG
        )
        await self._request("PUT", f"/tags/{tag_id}/assets", json={"ids": [asset_id]})

    async def tag_as_generated_once_read(
        self, asset_id: str, *, waits: UploadWaits = UploadWaits()
    ) -> bool:
        """Tag a fresh upload as this app's own once Immich has finished reading it.

        Tagging sooner loses the tag to Immich's own metadata job, and an untagged
        v3 film is never recognised as ours: it is kept beside its re-render and can
        come back as source footage. Waits for the read (a minute by default; `upload_waits`
        sizes it for a film), then tags, waits for Immich to finish reading the film again and
        reads the tag back, re-applying it if it did not stick. A tag written before the read
        is not verified.
        """
        if not await self._read_by_immich(asset_id, waits.read_polls):
            logger.warning("Immich had not read the uploaded film yet; tagging it anyway")
            await self.tag_as_generated(asset_id)
            return False
        for _ in range(_TAG_ATTEMPTS):
            await self.tag_as_generated(asset_id)
            await self._settled(asset_id, waits.quiet_polls)
            if await self._carries_generated_tag(asset_id):
                return True
        logger.warning("The provenance tag did not stay on the uploaded film")
        return False

    async def apply_label_once_read(
        self,
        asset_id: str,
        label: FilmLabel,
        *,
        description: bool = True,
        tags: bool = True,
        waits: UploadWaits = UploadWaits(),
    ) -> list[str]:
        """Give a fresh upload its description and tags once Immich has read it (#2505).

        The same timing as the provenance tag, for the same reason: Immich's metadata job
        overwrites both. Reads them back and applies them again if they did not stick;
        returns what still did not stay, as "description" and "tags". Written before
        Immich's read, both are returned as not kept: the read can still take them back.
        """
        wanted = {
            "description": description and bool(label.description),
            "tags": tags and bool(label.tags),
        }
        if not any(wanted.values()):
            return []
        read = await self._read_by_immich(asset_id, waits.read_polls)
        if not read:
            logger.warning("Immich had not read the uploaded film yet; describing it anyway")
        missing = [name for name, needed in wanted.items() if needed]
        for _ in range(_TAG_ATTEMPTS):
            # One write at a time, each left to settle: Immich rewrites the film's sidecar per
            # write, and two rewrites that overlap lose one of them.
            if wanted["tags"]:
                await self._put_tags(asset_id, label.tags)
                await self._settled(asset_id, waits.quiet_polls)
            if wanted["description"]:
                await self._request(
                    "PUT", f"/assets/{asset_id}", json={"description": label.description}
                )
                await self._settled(asset_id, waits.quiet_polls)
            missing = await self._label_not_kept(asset_id, label, wanted)
            if not read:
                return [name for name, needed in wanted.items() if needed]
            if not missing:
                return []
        return missing

    async def _put_tags(self, asset_id: str, values: Sequence[str]) -> None:
        tags = await self._request("PUT", "/tags", json={"tags": list(values)})
        ids = [tag["id"] for tag in tags if isinstance(tag, dict) and tag.get("value") in values]
        if ids:
            # Every tag in one write: one per tag made Immich rewrite the sidecar per tag, and
            # the rewrites collided (#2505 on a real server: the story tag was lost).
            await self._request("PUT", "/tags/assets", json={"tagIds": ids, "assetIds": [asset_id]})

    async def _settled(self, asset_id: str, quiet_polls: int) -> None:
        """Wait until Immich has stopped rewriting the asset: `quiet_polls` reads unchanged,
        within a minute or three quiet windows, whichever is longer.

        A check made sooner passes, then the read-back that lands after it takes back what
        was just written.
        """
        last, unchanged = None, 0
        for _ in range(max(_READ_WAIT_POLLS, 3 * quiet_polls)):
            stamp = (await self._request("GET", f"/assets/{asset_id}") or {}).get("updatedAt")
            unchanged = unchanged + 1 if stamp == last else 0
            if unchanged >= quiet_polls:
                return
            last = stamp
            await asyncio.sleep(_POLL_SECONDS)

    async def _label_not_kept(
        self, asset_id: str, label: FilmLabel, wanted: dict[str, bool]
    ) -> list[str]:
        asset = await self._request("GET", f"/assets/{asset_id}") or {}
        missing = []
        if wanted["description"]:
            kept = str((asset.get("exifInfo") or {}).get("description") or "").strip()
            if kept != label.description:
                missing.append("description")
        if wanted["tags"]:
            carried = {t.get("value") for t in asset.get("tags") or () if isinstance(t, dict)}
            if not set(label.tags) <= carried:
                missing.append("tags")
        return missing

    async def _read_by_immich(self, asset_id: str, polls: int = _READ_WAIT_POLLS) -> bool:
        for _ in range(polls):
            asset = await self._request("GET", f"/assets/{asset_id}") or {}
            if (asset.get("exifInfo") or {}).get("modifyDate"):
                return True
            await asyncio.sleep(_POLL_SECONDS)
        return False

    async def _carries_generated_tag(self, asset_id: str) -> bool:
        asset = await self._request("GET", f"/assets/{asset_id}") or {}
        return any(
            isinstance(tag, dict) and tag.get("value") == GENERATED_MEMORY_TAG
            for tag in asset.get("tags") or ()
        )

    async def generated_asset_ids(
        self, within: Sequence[DateRange] | None = None
    ) -> frozenset[str]:
        """The assets under this app's provenance tag; ``within`` may bound the search to
        those windows (see `generated_asset_tags.generated_asset_ids`)."""
        if self._get_key_capabilities is None:
            return await generated_asset_ids(self._request, within=within)
        capabilities = await self._get_key_capabilities()
        return await generated_asset_ids(
            self._request,
            can_read_tags=capabilities.allows("tag.read"),
            within=within,
        )

    async def trash_assets(self, asset_ids: list[str]) -> None:
        """Move assets to Immich's trash. Recoverable; never a hard delete."""
        await self._request("DELETE", "/assets", json={"ids": asset_ids, "force": False})

    async def upload_memory(
        self,
        video_path: Path,
        album_name: str | None = None,
        *,
        captured_at: datetime | None = None,
        label: FilmLabel | None = None,
    ) -> dict[str, Any]:
        """Upload a generated memory video, optionally adding it to an album.

        Reuses existing album if one with the same name exists. A `label` gives the film
        its description and tags once Immich has read it.
        """
        capabilities = await self._get_key_capabilities() if self._get_key_capabilities else None
        missing = list(capabilities.missing_upload) if capabilities else []
        # Told to the user, but no reason to keep an old render: the film itself arrived.
        label_missing = (
            [DESCRIBE]
            if label and label.description and capabilities and not capabilities.allows(DESCRIBE)
            else []
        )
        if capabilities is not None and not capabilities.allows("asset.upload"):
            return {
                "asset_id": None,
                "album_id": None,
                "delivery_complete": False,
                "missing_permissions": missing + label_missing,
                "warnings": ["not uploaded: the key lacks " + ", ".join(missing + label_missing)],
            }
        asset_id = await self.upload_asset(video_path, captured_at=captured_at)
        waits = upload_waits(video_path.stat().st_size)
        warnings: list[str] = []
        if missing:
            warnings.append("delivery incomplete: the key lacks " + ", ".join(missing))
        allows = capabilities.allows if capabilities else lambda _permission: True
        # A key that cannot label is reported, never an incomplete delivery: keys made
        # before films had labels lack `asset.update`, and treating that as incomplete
        # would keep every earlier render beside the new one. A label the key may write
        # but that did not stay leaves the delivery pending, so the retry writes it again.
        label_notes: list[str] = []
        await self._mark_delivery(asset_id, label, allows, (label_notes, warnings), waits)
        album_id = await self._album_delivery(asset_id, album_name, allows, warnings)
        complete = not warnings
        warnings.extend(label_notes)
        if not allows("asset.delete"):
            warnings.append("previous version kept: the key lacks asset.delete")
        elif not complete:
            warnings.append("previous version kept: delivery incomplete")
        else:
            try:
                await supersede_previous_renders(
                    self, album_id=album_id, filename=video_path.name, keep_asset_id=asset_id
                )
            except (OSError, RuntimeError, ValueError, KeyError) as exc:
                warnings.append(f"previous version kept: {exc}")
        for warning in warnings:
            logger.warning("%s", warning)
        return {
            "asset_id": asset_id,
            "album_id": album_id,
            "delivery_complete": complete,
            "missing_permissions": missing + label_missing,
            "warnings": warnings,
        }

    async def _mark_delivery(
        self,
        asset_id: str,
        label: FilmLabel | None,
        allows: Callable[[str], bool],
        reports: tuple[list[str], list[str]],
        waits: UploadWaits,
    ) -> None:
        """File the film under the provenance tag and give it its label.

        The provenance tag rides in the label's own tag write when there is one: every
        write makes Immich rewrite the film's sidecar, and each is waited out on its own
        (#2711). Otherwise it goes on alone.
        """
        carried = bool(label and label.tags) and not _tag_rights_missing(allows)
        if not carried:
            await self._tag_delivery(asset_id, allows, reports[1], waits)
        if label:
            await self._label_delivery(asset_id, label, allows, reports, waits, provenance=carried)

    async def _tag_delivery(
        self,
        asset_id: str,
        allows: Callable[[str], bool],
        warnings: list[str],
        waits: UploadWaits,
    ) -> None:
        if tag_missing := _tag_rights_missing(allows):
            warnings.append("uploaded without provenance: the key lacks " + ", ".join(tag_missing))
            return
        try:
            if not await self.tag_as_generated_once_read(asset_id, waits=waits):
                warnings.append("uploaded without verified provenance: the tag did not stay")
        except Exception as exc:
            warnings.append(f"uploaded without verified provenance: {exc}")

    async def _label_delivery(
        self,
        asset_id: str,
        label: FilmLabel,
        allows: Callable[[str], bool],
        reports: tuple[list[str], list[str]],
        waits: UploadWaits,
        *,
        provenance: bool = False,
    ) -> None:
        """Label the film; `reports` are (notes, warnings): a key that cannot label is a
        note, a label that did not stay is a warning that leaves the delivery pending.
        `provenance` writes the provenance tag with the label's tags, in the same write."""
        notes, warnings = reports
        tag_missing = _tag_rights_missing(allows)
        if label.tags and tag_missing:
            notes.append("uploaded without story tags: the key lacks " + ", ".join(tag_missing))
        if label.description and not allows(DESCRIBE):
            notes.append(f"uploaded without description: the key lacks {DESCRIBE}")
        written = replace(label, tags=(GENERATED_MEMORY_TAG, *label.tags)) if provenance else label
        try:
            not_kept = await self.apply_label_once_read(
                asset_id,
                written,
                description=allows(DESCRIBE),
                tags=not tag_missing,
                waits=waits,
            )
        except Exception as exc:
            if provenance:
                warnings.append(f"uploaded without verified provenance: {exc}")
            warnings.append(f"uploaded without a verified description and tags: {exc}")
            return
        if provenance and "tags" in not_kept:
            warnings.append("uploaded without verified provenance: the tag did not stay")
        warnings.extend(f"uploaded film's {name} did not stay" for name in not_kept)

    async def _album_delivery(
        self,
        asset_id: str,
        album_name: str | None,
        allows: Callable[[str], bool],
        warnings: list[str],
    ) -> str | None:
        if not album_name:
            return None
        album_id = None
        try:
            album_id = await self.find_album_by_name(album_name)
            if album_id is None:
                if not allows("album.create"):
                    warnings.append("album not created: the key lacks album.create")
                    return None
                album_id = await self.create_album(album_name)
            if allows("albumAsset.create"):
                await self.add_assets_to_album(album_id, [asset_id])
            else:
                warnings.append("film not added to album: the key lacks albumAsset.create")
        except Exception as exc:
            warnings.append(f"film not added to album: {exc}")
        return album_id


def _is_our_upload(asset: dict) -> bool:
    """Whether this app uploaded the asset, by the identity it stamps at upload."""
    return asset.get("deviceId") == _UPLOAD_DEVICE_ID and str(
        asset.get("deviceAssetId", "")
    ).startswith(f"{_UPLOAD_DEVICE_ID}-")


async def _tagged_ids(client) -> frozenset[str]:
    try:
        return await client.generated_asset_ids()
    except Exception as exc:  # WHY: unreadable tags only keep an old render
        logger.warning("Could not read the provenance tag; earlier renders kept: %s", exc)
        return frozenset()


async def supersede_previous_renders(
    client,
    *,
    album_id: str | None,
    filename: str,
    keep_asset_id: str,
) -> list[str]:
    """Trash earlier uploads of the same recipe, keeping the one just uploaded.

    The filename carries a hash of the recipe -- the memory type, range, duration
    and the exact clips in order -- so an identical name means an identical edit
    and the older copy is superseded rather than kept beside it. Without this, a
    library accumulates one indistinguishable file per run; eight of them is what
    prompted this.

    Deliberately narrow. Only assets inside the album we just uploaded to, with
    exactly this filename, never the asset we just created, and only ones
    carrying this app's own upload identity. A matching name is not proof of
    authorship -- a custom `output.filename` can name a video the user shot
    themselves, and trashing that is not ours to do. Ours means the v2 device
    identity or the provenance tag; v3 keeps no device identity, so there the
    tag alone decides, and a v3 render uploaded before tagging is kept. Immich's
    trash is recoverable, so this is reversible by the user.
    """
    if not album_id:
        return []

    assets = await client.list_album_assets(album_id)
    same_recipe = [
        asset
        for asset in assets
        if asset.get("originalFileName") == filename and asset.get("id") != keep_asset_id
    ]
    tagged = (
        await _tagged_ids(client)
        if any(not _is_our_upload(asset) for asset in same_recipe)
        else frozenset()
    )
    superseded = [
        asset["id"] for asset in same_recipe if _is_our_upload(asset) or asset["id"] in tagged
    ]
    if superseded:
        await client.trash_assets(superseded)
    return superseded
