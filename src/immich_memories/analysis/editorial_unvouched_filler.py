"""A no-model film goes short rather than keep filler that shows nothing.

The rules draft fills its slots from the material, not from what vouches for each picture, so
in a quiet month it reaches past its indicators. A picture with no indicator of its own (no
star, no video or playing motion, no person Immich knows) is only
there as filler, and when the frame head reads it as carrying nothing (a lone object, an empty
room, a body part, a screen or a document) it leaves the cut. Nothing takes its place: short
beats a guess.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from immich_memories.analysis.editorial_carrier_eligibility import NOTHING_KINDS
from immich_memories.analysis.editorial_intent import voiced_era_of

# A screen or document is evidence a film can carry when something vouches for it; as filler
# it shows nothing a viewer came for.
SHOWS_NOTHING_AS_FILLER = NOTHING_KINDS | {"screen_or_document"}
MOVING_KINDS = frozenset({"video", "live-motion"})


@dataclass(frozen=True)
class FillerEvidence:
    frame_kind_of: Callable[[str], str | None]
    known_person: Callable[[str], bool]
    protected: frozenset[str] = frozenset()
    # The partition of a capture time, for a film that gives every partition a voice.
    era_of: Callable[[str], str | None] | None = None


def owner_vouches_for(carrier: Mapping[str, Any], evidence: FillerEvidence) -> bool:
    """Whether the library itself says this picture matters: a star, a recorded video, a
    person Immich knows, or an owner requirement.

    A Live Photo's motion is not one: the phone records it with every still, so it says
    nothing the photographer chose.
    """
    asset = carrier["asset_id"]
    return (
        bool(carrier.get("favourite"))
        or carrier.get("kind") == "video"
        or asset in evidence.protected
        or evidence.known_person(asset)
    )


def _has_indicator(carrier: dict, evidence: FillerEvidence) -> bool:
    return owner_vouches_for(carrier, evidence) or carrier.get("kind") in MOVING_KINDS


def drop_unvouched_filler(
    carriers: Sequence[dict], evidence: FillerEvidence
) -> tuple[list[dict], list[dict]]:
    """Split a settled cut into the shots it keeps and the filler it drops.

    Only removes: a shot with any indicator, or with no frame reading, is kept as it is. A film
    that promised every partition a voice keeps one shot of a partition the drop would silence.
    """
    filler = {
        c["asset_id"]
        for c in carriers
        if evidence.frame_kind_of(c["asset_id"]) in SHOWS_NOTHING_AS_FILLER
        and not _has_indicator(c, evidence)
    }
    filler -= _last_voices(carriers, filler, evidence.era_of)
    kept = [c for c in carriers if c["asset_id"] not in filler]
    dropped = [c for c in carriers if c["asset_id"] in filler]
    return kept, dropped


def _last_voices(
    carriers: Sequence[dict], filler: set[str], era_of: Callable[[str], str | None] | None
) -> set[str]:
    """One shot of every partition whose every shot is filler: the one that stands best, the
    earlier on a tie."""
    if era_of is None:
        return set()
    shots_of: dict[str, list[dict]] = {}
    for carrier in carriers:
        if (era := era_of(str(carrier["taken"]))) is not None:
            shots_of.setdefault(era, []).append(carrier)
    return {
        min(shots, key=lambda c: (-(c.get("standing") or 0), str(c["taken"])))["asset_id"]
        for shots in shots_of.values()
        if all(c["asset_id"] in filler for c in shots)
    }


def filler_evidence(source) -> FillerEvidence:
    """What vouches for a picture of a planning input, and what its frame head read."""

    def frame_kind_of(asset_id: str) -> str | None:
        record = source.audience_annotations.get(asset_id)
        return dict(record.heads).get("frame_kind") if record is not None else None

    def known_person(asset_id: str) -> bool:
        asset = source.assets.get(asset_id)
        return bool(asset is not None and asset.people)

    return FillerEvidence(
        frame_kind_of=frame_kind_of,
        known_person=known_person,
        protected=frozenset(source.owner_required_asset_ids),
        era_of=voiced_era_of(source.intent),
    )
