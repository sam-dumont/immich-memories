"""One picture stored as several files, folded back into one before the editor sees it.

A shared album carries no originals, so a curated shot reaches the library twice: the camera's
full-size file and the album's downscale (about 2048 px), with the same capture instant to the
millisecond and the same camera file name. Immich keeps both because it only refuses
byte-identical uploads. Measured on one February: 352 of 2,028 files were such copies.

Which *picture* wins a moment is the editor's question. Which *file* carries it is arithmetic
for a shared-album downscale, but not for an iOS edit: the same camera file, re-rendered after a
crop or a filter, re-uploaded under its own name at its own capture second (Immich has no replace
endpoint, so the edit lands as a second file; the original stays). There the newest file -- not
the biggest -- is the picture the owner meant, so long as it is not itself a shared-album
downscale (pixel ratio under 0.5 of the group's largest; those still lose on pixels alone). A
star belongs to the picture, not to the file it was set on, so the kept file takes it from any
copy.

The camera's name is what makes two files one picture, together with its exact capture instant
and, where EXIF carries one, its camera model -- a forwarded copy and an edited re-render can
share a name and a second without sharing a model. A forwarded copy loses the name entirely: the
file comes back under a UUID, still on its capture second. There the pixels decide, and only
there, because the two signals fail on their own. A messaging app dates a received batch to the
second it arrived, so six different photos can share an instant; and an 8x8 hash cannot tell two
frames of one burst apart (123 same-second camera pairs sat 0 bits apart). Measured on one
February, the 13 forwarded copies sat 0 or 1 bit from their camera file and the different photos
14 or more.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from itertools import combinations
from pathlib import PurePath

from immich_memories.analysis.duplicate_hashing import hamming_distance
from immich_memories.api.models import Asset

# A forwarded copy is at most this many bits from its camera file; different photos sat 14+ apart.
FORWARDED_COPY_BITS = 2
_UUID_NAME = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)
# Below this share of the group's largest file, a copy is a shared-album downscale, not an
# edit -- it never competes for "newest wins", only for pixels.
_EDIT_PIXEL_RATIO = 0.5


def _capture_instant(asset: Asset) -> object:
    """EXIF's own capture time where present; an edit's re-render keeps it unchanged.

    `getattr` guards callers (`special_day_scan.py`) that pass a lighter stand-in for an
    asset, with no promise of the full `ExifInfo` shape.
    """
    exif = asset.exif_info
    return getattr(exif, "date_time_original", None) or asset.file_created_at


def _camera_model(asset: Asset) -> str | None:
    exif = asset.exif_info
    return getattr(exif, "model", None) if exif else None


def _picture_key(asset: Asset) -> tuple[object, ...] | None:
    name = PurePath(asset.original_file_name).stem.upper()
    if not name:
        return None
    return (asset.type, _capture_instant(asset), name, _camera_model(asset))


def _pixels(asset: Asset) -> int:
    return asset.width * asset.height


def _forwarded(asset: Asset) -> bool:
    return bool(_UUID_NAME.match(PurePath(asset.original_file_name).stem))


def _forwarded_pairs(
    pictures: list[Asset], hash_of: Callable[[Asset], str | None]
) -> list[tuple[Asset, Asset]]:
    """Same-second pairs where one file came back under a UUID and the pixels agree."""
    by_second: defaultdict[tuple[object, ...], list[Asset]] = defaultdict(list)
    for asset in pictures:
        by_second[(asset.type, asset.file_created_at.replace(microsecond=0))].append(asset)
    pairs = []
    for files in by_second.values():
        for left, right in combinations(files, 2):
            if not (_forwarded(left) or _forwarded(right)):
                continue
            left_hash, right_hash = hash_of(left), hash_of(right)
            if (
                left_hash
                and right_hash
                and hamming_distance(left_hash, right_hash) <= (FORWARDED_COPY_BITS)
            ):
                pairs.append((left, right))
    return pairs


def _grouped(assets: list[Asset], pairs: Iterable[tuple[Asset, Asset]]) -> list[list[Asset]]:
    """The files each pair joins, merged into one group per picture."""
    parent = {asset.id: asset.id for asset in assets}

    def root(key: str) -> str:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for left, right in pairs:
        parent[root(left.id)] = root(right.id)
    groups: defaultdict[str, list[Asset]] = defaultdict(list)
    for asset in assets:
        groups[root(asset.id)].append(asset)
    return list(groups.values())


def _keeper(group: list[Asset]) -> Asset:
    """The file that carries the group's picture: the newest edit-shaped file, or else pixels.

    A shared-album downscale (pixel ratio under `_EDIT_PIXEL_RATIO` of the group's largest)
    never wins -- it is excluded before the comparison. Among what is left (the original and
    any iOS edit of it, all full-size), the newest `fileModifiedAt` is the picture the owner
    last touched; the asset id only breaks an exact tie, so the choice is never arbitrary in
    practice.
    """
    largest = max(_pixels(asset) for asset in group)
    contenders = [
        asset for asset in group if largest == 0 or _pixels(asset) / largest >= _EDIT_PIXEL_RATIO
    ]
    # getattr guards a caller's lighter stand-in for an asset (special_day_scan.py), which
    # never carries an edit and so never promised its own fileModifiedAt.
    return max(
        contenders,
        key=lambda asset: (
            getattr(asset, "file_modified_at", None) or asset.file_created_at,
            asset.id,
        ),
    )


def picture_copies(
    assets: Iterable[Asset], *, hash_of: Callable[[Asset], str | None] | None = None
) -> dict[str, Asset]:
    """Each copy's id mapped to the file that carries its picture: see `_keeper`.

    Files are one picture when they share the camera's file name, the kind (photo or video),
    the capture instant and, where EXIF carries one, the camera model. With `hash_of` (a cached
    preview's hash, or None when there is none), a file forwarded back under a UUID name joins
    the picture it shares a second and its pixels with. A picture stored once has no entry.
    """
    files = list(assets)
    named: defaultdict[tuple[object, ...], list[Asset]] = defaultdict(list)
    for asset in files:
        if (key := _picture_key(asset)) is not None:
            named[key].append(asset)
    pairs = [(group[0], other) for group in named.values() for other in group[1:]]
    if hash_of is not None:
        pairs += _forwarded_pairs(files, hash_of)
    copies: dict[str, Asset] = {}
    for group in _grouped(files, pairs):
        if len(group) < 2:
            continue
        keeper = _keeper(group)
        copies.update({asset.id: keeper for asset in group if asset.id != keeper.id})
    return copies


def starred_keepers(copies: Mapping[str, Asset], assets: Iterable[Asset]) -> set[str]:
    """The kept files whose picture carries a star on any of its files."""
    return {copies[asset.id].id for asset in assets if asset.id in copies and asset.is_favorite}


def group_members(copies: Mapping[str, Asset]) -> dict[str, frozenset[str]]:
    """Every id of a picture, keyed by every id of that same picture (the keeper included).

    A picture stored once has no entry. An album-scoped ask that names one file of an edited
    picture meant the picture, whichever file was kept -- this is how a caller checks that
    without remapping ids, since the keeper itself can change which file it is.
    """
    groups: defaultdict[str, set[str]] = defaultdict(set)
    for copy_id, keeper in copies.items():
        groups[keeper.id].update((copy_id, keeper.id))
    return {member: frozenset(members) for members in groups.values() for member in members}


def copy_reason(keeper: Asset) -> str:
    """Why a copy is not a source: its picture plays from the full-size file."""
    return (
        f"another file of the same picture ({keeper.original_file_name}); the full-size file plays"
    )
