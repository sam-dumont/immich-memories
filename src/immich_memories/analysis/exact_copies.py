"""The same bytes under different asset IDs, counted once.

Two accounts on one server each hold their own copy of a shared picture: a partner's
phone uploads it too, or a shared album hands it over. Immich gives each copy its own
UUID, and the same UUID seen twice is already one object (`_coalesce_sources`). This is
the second step: distinct UUIDs whose SHA-1 checksum is equal and whose media kind is
equal are one item.

Only a checksum proves identity here. A missing or unreadable one leaves the copy alone,
and a similar picture, an edited export or a re-encode has different bytes, so none of
them folds. Which copy stands for the item: a favourited one, then the primary owner's,
then the smallest (owner id, asset id), so response order never decides it.

A Live Photo still's checksum says nothing about its motion. The kept still keeps its own
companion; an absorbed still takes its companion with it, recorded on its reference, so
nothing plays another copy's motion and no orphaned half reaches the pool as a video.
"""

from __future__ import annotations

import base64
import binascii
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from immich_memories.analysis.source_filter import asset_id_of, asset_of
from immich_memories.api.models import Asset, VideoClipInfo

_SHA1_BYTES = 20


@dataclass(frozen=True)
class CopyReference:
    """One raw copy of an item, with the Live Photo motion it came with."""

    owner_id: str
    asset_id: str
    companion_id: str | None


@dataclass(frozen=True)
class CopyGroup:
    """Every raw copy one kept item absorbed, under a key that is not an asset id."""

    content_key: str
    representative_id: str
    references: tuple[CopyReference, ...]


@dataclass(frozen=True)
class FoldedPool:
    """The pool with each exact copy counted once, and what each kept item stands for."""

    pool: tuple[Asset | VideoClipInfo, ...]
    groups: tuple[CopyGroup, ...]

    def kept_ids(self, asset_ids: Sequence[str]) -> tuple[str, ...]:
        """Each id as the copy that stands for its picture, in order and without repeats.

        An owner who ticked or excluded one copy meant the picture, whichever copy is kept.
        """
        kept = {
            reference.asset_id: group.representative_id
            for group in self.groups
            for reference in group.references
        }
        return tuple(dict.fromkeys(kept.get(asset_id, asset_id) for asset_id in asset_ids))


def fold_exact_copies(
    sources: Sequence[Asset | VideoClipInfo], *, primary_owner_id: str | None
) -> FoldedPool:
    """Fold distinct asset IDs with an equal SHA-1 and media kind into one item.

    The kept item carries the union of its copies' people, since each account tags its
    own copy. The pool comes back in (capture time, asset id) order whatever the order
    the pages arrived in. Live Photo motion halves never fold on their own: they follow
    their still.
    """
    companions = {asset_of(source).live_photo_video_id for source in sources} - {None}
    by_content: defaultdict[str, list[Asset | VideoClipInfo]] = defaultdict(list)
    for source in sources:
        asset = asset_of(source)
        digest = _sha1_digest(asset.checksum)
        if digest is not None and asset.id not in companions:
            by_content[f"{asset.type.value.lower()}:sha1:{digest.hex()}"].append(source)
    groups: list[CopyGroup] = []
    replaced: dict[str, Asset | VideoClipInfo] = {}
    absorbed: set[str] = set()
    for content_key, copies in by_content.items():
        if len(copies) < 2:
            continue
        ordered = sorted(copies, key=lambda source: _precedence(source, primary_owner_id))
        kept, rest = ordered[0], ordered[1:]
        replaced[asset_id_of(kept)] = _with_people_of(kept, ordered)
        absorbed.update(asset_id_of(source) for source in rest)
        groups.append(
            CopyGroup(
                content_key=content_key,
                representative_id=asset_id_of(kept),
                references=tuple(_reference(source) for source in ordered),
            )
        )
    absorbed |= _orphaned_companions(sources, absorbed, groups)
    pool = tuple(
        sorted(
            (
                replaced.get(asset_id_of(source), source)
                for source in sources
                if asset_id_of(source) not in absorbed
            ),
            key=lambda source: (asset_of(source).file_created_at, asset_id_of(source)),
        )
    )
    return FoldedPool(pool, tuple(sorted(groups, key=lambda group: group.content_key)))


def _sha1_digest(checksum: str | None) -> bytes | None:
    """The 20 bytes Immich sends base64-encoded, or None for anything that is not a SHA-1."""
    if not checksum or not checksum.strip():
        return None
    try:
        digest = base64.b64decode(checksum.strip(), validate=True)
    except (binascii.Error, ValueError):
        return None
    return digest if len(digest) == _SHA1_BYTES else None


def _precedence(
    source: Asset | VideoClipInfo, primary_owner_id: str | None
) -> tuple[bool, bool, str, str]:
    asset = asset_of(source)
    return (
        not asset.is_favorite,
        primary_owner_id is None or asset.owner_id != primary_owner_id,
        asset.owner_id,
        asset.id,
    )


def _reference(source: Asset | VideoClipInfo) -> CopyReference:
    asset = asset_of(source)
    return CopyReference(asset.owner_id, asset.id, asset.live_photo_video_id)


def _with_people_of(
    kept: Asset | VideoClipInfo, copies: Sequence[Asset | VideoClipInfo]
) -> Asset | VideoClipInfo:
    asset = asset_of(kept)
    people = {person.id: person for person in asset.people}
    for copy in copies:
        for person in asset_of(copy).people:
            people.setdefault(person.id, person)
    if len(people) == len(asset.people):
        return kept
    merged = asset.model_copy(update={"people": list(people.values())})
    return kept.model_copy(update={"asset": merged}) if isinstance(kept, VideoClipInfo) else merged


def _orphaned_companions(
    sources: Sequence[Asset | VideoClipInfo], absorbed: set[str], groups: Sequence[CopyGroup]
) -> set[str]:
    """Motion halves whose only still was absorbed: they leave with it."""
    claimed = {
        asset_of(source).live_photo_video_id
        for source in sources
        if asset_id_of(source) not in absorbed
    }
    return {
        reference.companion_id
        for group in groups
        for reference in group.references
        if reference.asset_id != group.representative_id
        and reference.companion_id is not None
        and reference.companion_id not in claimed
    }
