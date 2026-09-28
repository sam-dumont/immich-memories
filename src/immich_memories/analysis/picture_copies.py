"""One picture stored as several files, folded back into one before the editor sees it.

A shared album carries no originals, so a curated shot reaches the library twice: the camera's
full-size file and the album's downscale (about 2048 px), with the same capture instant to the
millisecond and the same camera file name. Immich keeps both because it only refuses
byte-identical uploads. Measured on one February: 352 of 2,028 files were such copies.

Which *picture* wins a moment is the editor's question. Which *file* carries it is arithmetic:
the one with the most pixels. A star belongs to the picture, not to the file it was set on, so
the kept file takes it from any copy.

The camera's name is what makes two files one picture. A forwarded copy loses it: the file comes
back under a UUID, still on its capture second. There the pixels decide, and only there, because
the two signals fail on their own. A messaging app dates a received batch to the second it
arrived, so six different photos can share an instant; and an 8x8 hash cannot tell two frames of
one burst apart (123 same-second camera pairs sat 0 bits apart). Measured on one February, the 13
forwarded copies sat 0 or 1 bit from their camera file and the different photos 14 or more.
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


def _picture_key(asset: Asset) -> tuple[object, ...] | None:
    name = PurePath(asset.original_file_name).stem.upper()
    if not name:
        return None
    return (asset.type, asset.file_created_at, name)


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


def picture_copies(
    assets: Iterable[Asset], *, hash_of: Callable[[Asset], str | None] | None = None
) -> dict[str, Asset]:
    """Each copy's id mapped to the file that carries its picture: the one with the most pixels.

    Files are one picture when they share the camera's file name, the kind (photo or video) and
    the capture instant. With `hash_of` (a cached preview's hash, or None when there is none), a
    file forwarded back under a UUID name joins the picture it shares a second and its pixels
    with. A picture stored once has no entry.
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
        keeper = max(group, key=lambda asset: (_pixels(asset), asset.id))
        copies.update({asset.id: keeper for asset in group if asset.id != keeper.id})
    return copies


def starred_keepers(copies: Mapping[str, Asset], assets: Iterable[Asset]) -> set[str]:
    """The kept files whose picture carries a star on any of its files."""
    return {copies[asset.id].id for asset in assets if asset.id in copies and asset.is_favorite}


def copy_reason(keeper: Asset) -> str:
    """Why a copy is not a source: its picture plays from the full-size file."""
    return (
        f"another file of the same picture ({keeper.original_file_name}); the full-size file plays"
    )
