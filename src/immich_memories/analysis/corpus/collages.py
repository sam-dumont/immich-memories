"""A collage in a film's pool: out when its day holds the pictures it repeats, never the opener.

A phone's collage app tiles a few frames of one moment on a page and saves the page as a new
picture. A multi-person film opened on one: four near-identical frames of a newborn, the frames
themselves in the library beside it (#2773). The page is no moment of its own: when the day it was
made on holds other pictures of its people, those are the moment and the collage is left out. A
collage alone on its day can still be an ordinary shot, but a film never opens on one, and a film
is chronological, so a collage that nothing in the pool comes before is left out too.

Only a still without a camera exposure is read: a collage is made, not taken, and a photograph
that carries its shutter speed is no page of tiles. The reading itself is the pixel check of
`corpus.forwarded_checks.looks_composed`, at no outside call.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime
from typing import Any

from immich_memories.api.models import AssetType

REPEATS_ITS_DAY = "a collage of a moment whose own pictures the film holds"
WOULD_OPEN = "a collage, and nothing comes before it: a film never opens on one"


def collage_exclusions(
    assets: Mapping[str, Any],
    checked: Iterable[str],
    *,
    composed: Callable[[str], bool],
) -> dict[str, str]:
    """The collages among `checked` the film leaves out, with the reason for each.

    `assets` is the film's whole pool; `composed(asset_id)` reads one preview.
    """
    collages = {
        asset_id for asset_id in checked if _made_still(assets.get(asset_id)) and composed(asset_id)
    }
    if not collages:
        return {}
    others = [asset for asset_id, asset in assets.items() if asset_id not in collages]
    earliest = min((_instant(asset) for asset in others), default=None)
    reasons: dict[str, str] = {}
    for asset_id in sorted(collages):
        collage = assets[asset_id]
        if any(_same_moment(collage, other) for other in others):
            reasons[asset_id] = REPEATS_ITS_DAY
        elif earliest is None or _instant(collage) <= earliest:
            reasons[asset_id] = WOULD_OPEN
    return reasons


def preview_collage_check(read_preview: Callable[[str], bytes | None]) -> Callable[[str], bool]:
    """`composed` for `collage_exclusions`: whether a picture's preview is a page of tiles, each
    preview read once; a picture with no preview is no collage."""
    from functools import cache

    from immich_memories.analysis.corpus.forwarded_checks import looks_composed

    @cache
    def composed(asset_id: str) -> bool:
        payload = read_preview(asset_id)
        return payload is not None and looks_composed(payload)

    return composed


def _made_still(asset: Any) -> bool:
    if asset is None or getattr(asset, "type", None) != AssetType.IMAGE:
        return False
    exif = getattr(asset, "exif_info", None)
    return not (exif and getattr(exif, "exposure_time", None))


def _same_moment(collage: Any, other: Any) -> bool:
    """Whether `other` is a picture of the collage's own day and, when it names people, theirs."""
    if _day(other) != _day(collage):
        return False
    people = _people(collage)
    return not people or bool(people & _people(other))


def _people(asset: Any) -> set[str]:
    return {person.id for person in getattr(asset, "people", None) or [] if person.id}


def _day(asset: Any) -> date:
    return _clock(asset).date()


def _instant(asset: Any) -> datetime:
    return asset.file_created_at


def _clock(asset: Any) -> datetime:
    return getattr(asset, "local_taken_at", None) or asset.file_created_at
