"""Stack members folded into their primary before the editor sees them.

Immich's mobile app auto-stacks a photo edit with its original
(immich-app/immich#31082): `POST /stacks {assetIds: [newEditId, previousId]}`,
and `StackRepository.create` makes `assetIds[0]` -- the edit -- the stack's
primary. A user-made stack (a burst, a RAW+JPEG pair) has the same shape: one
primary, several members. Search returns every member with no stack
information (`withStacked` only drops both or neither), so without this an
edit and its original both reach the editor, or `picture_copies.py`'s
pixel-count rule keeps the larger original over a cropped edit.

The stack says which file plays; no pixel count or file name is weighed here.
A star on any member moves to the primary, the same as a star on any copy of
one picture already does (`picture_copies.starred_keepers`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from immich_memories.api.models import Asset


def fold_stacks(assets: Iterable[Asset], stack_of: Mapping[str, str]) -> dict[str, Asset]:
    """Each stack member's id mapped to its stack's primary asset.

    ``stack_of`` is member asset id -> primary asset id, built from `GET
    /stacks`. The primary is never a key of its own mapping, so it is never
    folded into itself; a member whose primary did not reach this pool (a
    different library scope, or a read that failed) is left alone.
    """
    by_id = {asset.id: asset for asset in assets}
    folded: dict[str, Asset] = {}
    for asset in by_id.values():
        primary_id = stack_of.get(asset.id)
        if primary_id is None or primary_id == asset.id or primary_id not in by_id:
            continue
        folded[asset.id] = by_id[primary_id]
    return folded


def starred_primaries(folded: Mapping[str, Asset], assets: Iterable[Asset]) -> set[str]:
    """The stack primaries whose stack carries a star on any of its members."""
    return {folded[asset.id].id for asset in assets if asset.id in folded and asset.is_favorite}


def stack_reason(primary: Asset) -> str:
    """Why a stack member is not a source: its stack's primary plays."""
    return (
        f"another file of the same stack ({primary.original_file_name}); the stack's primary plays"
    )
