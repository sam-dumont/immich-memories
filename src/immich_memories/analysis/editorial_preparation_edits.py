"""What a picture owes again once Immich's own editor has touched it (#2114).

Pixel, head and caption facts, and its cached preview, were all read from the render
in place before the edit. None of them are keyed by anything that changes when only
the edit does, so an edit after a warm run has to be told apart from "already answered"
explicitly, by the asset ids `edited_mismatch_ids` names as flipped.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from immich_memories.api.models import Asset


def owing_flipped_edits(
    missing: dict[str, tuple[str, ...]],
    flipped_edits: frozenset[str],
    pixel_producer_key: str,
    description_model: str,
    head_versions: Mapping[str, str],
) -> dict[str, tuple[str, ...]]:
    """A picture whose edit state changed since it was last banked owes every
    content-derived producer again, whether or not the store already answered it.

    Nothing here is keyed by anything that changes when only the edit does, so an
    already-banked answer reads as settled unless this adds it back as owed.
    """
    if not flipped_edits:
        return missing
    keys = (
        f"description:{description_model}",
        f"pixel:{pixel_producer_key}",
        *(f"head:{head}@{version}" for head, version in head_versions.items()),
    )
    result = missing.copy()
    for key in keys:
        result[key] = tuple(dict.fromkeys((*result.get(key, ()), *flipped_edits)))
    return result


def ids_owing_faces(
    unread: Sequence[str], named: Sequence[str], flipped_edits: frozenset[str]
) -> tuple[str, ...]:
    """`unread` plus any named picture whose edit state just flipped: its banked face
    boxes were read off the unedited render, so the store's answer no longer counts."""
    return tuple(dict.fromkeys((*unread, *(aid for aid in named if aid in flipped_edits))))


def edited_preview_targets(
    source: Sequence[Asset], flipped_edits: frozenset[str]
) -> dict[str, bool]:
    """Which asset ids must bypass the preview cache's plain hit check.

    A currently edited picture always does: its cache slot may still hold an earlier
    run's unedited preview. So does one whose edit state just flipped back to unedited --
    `is_edited` alone would read that reverted picture as still a good cache hit, when
    the file on disk is the edited render it needs to leave behind.
    """
    return {asset.id: asset.is_edited or asset.id in flipped_edits for asset in source}
