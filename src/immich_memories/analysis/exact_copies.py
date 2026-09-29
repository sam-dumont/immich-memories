"""The same bytes under different asset IDs, counted once.

Two accounts on one server each hold their own copy of a shared picture: a partner's
phone uploads it too, or a shared album hands it over. Immich gives each copy its own
UUID, and the same UUID seen twice is already one object (`_coalesce_sources`). This is
the second step: distinct UUIDs whose SHA-1 checksum is equal and whose media kind is
equal are one item.

Only a checksum proves identity here. A missing or unreadable one leaves the copy alone,
and a similar picture, an edited export or a re-encode has different bytes, so none of
them folds. Which copy stands for the item: a Live Photo whose motion half is in the pool,
since a plain copy of the same still has lost its motion; then a favourited one, then the
primary owner's, then the smallest (owner id, asset id), so response order never decides it.
Keeping the Live copy never decides that it moves: its measured motion does, later, and a
Live Photo that barely moves is shown as the still the plain copy would have been.

A Live Photo still's checksum says nothing about its motion. The kept still keeps its own
companion; an absorbed still takes its companion with it, recorded on its reference, so
nothing plays another copy's motion and no orphaned half reaches the pool as a video.
A plain video whose bytes equal a motion half in the pool is that Live Photo saved another
way: it folds into the Live Photo, which stays. A star on any file of the picture, motion
halves included, stars the kept item.
"""

from __future__ import annotations

import base64
import binascii
from collections import defaultdict
from collections.abc import Mapping, Sequence
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
    own copy, and a star on any file of the picture, since each account stars its own.
    The pool comes back in (capture time, asset id) order whatever the order the pages
    arrived in. Live Photo motion halves never fold on their own: they follow their still.
    A standalone video holding the same bytes as a motion half in the pool folds into that
    Live Photo, so the moment is the Live Photo once and not a second, plain video.
    """
    by_id = {asset_id_of(source): source for source in sources}
    members = _copy_members(sources, primary_owner_id)
    groups: list[CopyGroup] = []
    replaced: dict[str, Asset | VideoClipInfo] = {}
    absorbed: set[str] = set()
    for representative_id, (content_key, ordered) in members.items():
        replaced[representative_id] = _standing_for(ordered, by_id)
        absorbed.update(asset_id_of(source) for source in ordered[1:])
        groups.append(
            CopyGroup(
                content_key=content_key,
                representative_id=representative_id,
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


def _copy_members(
    sources: Sequence[Asset | VideoClipInfo], primary_owner_id: str | None
) -> dict[str, tuple[str, list[Asset | VideoClipInfo]]]:
    """Each kept item's id, with its content key and every copy it stands for, kept first.

    Copies of one kind fold first. A video whose bytes are a Live Photo's motion then joins
    the item that Live Photo's still belongs to, behind the still, so the still is kept.
    """
    companions = {asset_of(source).live_photo_video_id for source in sources} - {None}
    by_content: defaultdict[str, list[Asset | VideoClipInfo]] = defaultdict(list)
    for source in sources:
        key = _content_key(source)
        if key is not None and asset_id_of(source) not in companions:
            by_content[key].append(source)
    motions = _live_photos_by_motion(sources)
    by_id = {asset_id_of(source): source for source in sources}

    def precedence(source: Asset | VideoClipInfo) -> tuple[bool, bool, bool, str, str]:
        return _precedence(source, primary_owner_id, by_id)

    members: dict[str, tuple[str, list[Asset | VideoClipInfo]]] = {}
    for content_key, copies in by_content.items():
        if content_key not in motions and len(copies) > 1:
            ordered = sorted(copies, key=precedence)
            members[asset_id_of(ordered[0])] = (content_key, ordered)
    kept_as = {
        asset_id_of(copy): representative_id
        for representative_id, (_key, ordered) in members.items()
        for copy in ordered
    }
    # Key order, not page order, decides where each motion-equal video lands in its group.
    for content_key, videos in sorted(by_content.items()):
        if content_key not in motions:
            continue
        still = min(
            (
                by_id[kept_as.get(asset_id_of(live), asset_id_of(live))]
                for live in motions[content_key]
            ),
            key=precedence,
        )
        key, ordered = members.get(asset_id_of(still), (content_key, [still]))
        members[asset_id_of(still)] = (key, [*ordered, *sorted(videos, key=precedence)])
    return members


def _content_key(source: Asset | VideoClipInfo) -> str | None:
    asset = asset_of(source)
    digest = _sha1_digest(asset.checksum)
    return None if digest is None else f"{asset.type.value.lower()}:sha1:{digest.hex()}"


def _live_photos_by_motion(
    sources: Sequence[Asset | VideoClipInfo],
) -> dict[str, list[Asset | VideoClipInfo]]:
    """Live Photo stills under the content key of the motion half they came with."""
    by_id = {asset_id_of(source): source for source in sources}
    stills: defaultdict[str, list[Asset | VideoClipInfo]] = defaultdict(list)
    for source in sources:
        motion = by_id.get(asset_of(source).live_photo_video_id or "")
        key = None if motion is None else _content_key(motion)
        if key is not None:
            stills[key].append(source)
    return stills


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
    source: Asset | VideoClipInfo,
    primary_owner_id: str | None,
    by_id: Mapping[str, Asset | VideoClipInfo],
) -> tuple[bool, bool, bool, str, str]:
    """A Live copy whose motion half is in the pool first: a companion that never arrived
    counts as no motion, so the kept copy never points at a missing half."""
    asset = asset_of(source)
    return (
        (asset.live_photo_video_id or "") not in by_id,
        not asset.is_favorite,
        primary_owner_id is None or asset.owner_id != primary_owner_id,
        asset.owner_id,
        asset.id,
    )


def _reference(source: Asset | VideoClipInfo) -> CopyReference:
    asset = asset_of(source)
    return CopyReference(asset.owner_id, asset.id, asset.live_photo_video_id)


def _standing_for(
    copies: Sequence[Asset | VideoClipInfo], by_id: Mapping[str, Asset | VideoClipInfo]
) -> Asset | VideoClipInfo:
    """The kept copy with every copy's people and a star if any file of the picture has one."""
    kept = copies[0]
    asset = asset_of(kept)
    people = {person.id: person for person in asset.people}
    for copy in copies:
        for person in asset_of(copy).people:
            people.setdefault(person.id, person)
    starred = any(_starred(copy, by_id) for copy in copies)
    if len(people) == len(asset.people) and starred == asset.is_favorite:
        return kept
    merged = asset.model_copy(update={"people": list(people.values()), "is_favorite": starred})
    return kept.model_copy(update={"asset": merged}) if isinstance(kept, VideoClipInfo) else merged


def _starred(copy: Asset | VideoClipInfo, by_id: Mapping[str, Asset | VideoClipInfo]) -> bool:
    """A star on the copy, or on the Live Photo motion it came with."""
    asset = asset_of(copy)
    motion = by_id.get(asset.live_photo_video_id or "")
    return asset.is_favorite or (motion is not None and asset_of(motion).is_favorite)


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
