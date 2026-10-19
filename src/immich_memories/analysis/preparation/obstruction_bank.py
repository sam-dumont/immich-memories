"""Read the finger-over-the-lens head off patch tokens the heads pass already holds (#2022).

A rank-only head: a picture never measured for it, or whose preview could not be read,
renders exactly as it did before this head existed (no warning, no change in order). It
never runs an encoder of its own: `preparation.heads` hands it the tokens of the one
DINOv2 call each preview and each sampled video frame pays for.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from immich_memories.analysis.clips.bound_sample import source_metadata_digest
from immich_memories.analysis.facts.obstruction import (
    OBSTRUCTED_LABEL,
    decide,
    denormalized_crop_bgr,
    obstructed_seconds,
)
from immich_memories.api.models import Asset
from immich_memories.processing.frame_sampling import even_timestamps
from immich_memories.store.cut_measurements import PendingMeasurements
from immich_memories.triage.heads import HeadFact, PatchHeadBundle

# #2022: the method string a `motion_residuals` producer key names; FRAME_WIDTH=768 is
# `preparation.detector_frames.FRAME_WIDTH`, the frames this reuses rather than
# re-sampling. The timestamps are reconstructed with the same even spacing the detector
# frame sampler uses, since the sampler itself does not carry its chosen seconds forward.
OBSTRUCTION_FRAME_PRODUCER = "edge-obstruction-v1@detector-frames-768"


def obstruction_facts(
    bundle: PatchHeadBundle, pixels: np.ndarray, patches: np.ndarray
) -> list[HeadFact]:
    """One obstruction fact per picture, from its preprocessed pixels and patch tokens."""
    probability_maps = bundle.patch_probabilities(patches)
    facts = []
    for row in range(len(pixels)):
        reading = decide(denormalized_crop_bgr(pixels[row]), probability_maps[row])
        facts.append(
            HeadFact(
                head=bundle.name,
                label=reading.label,
                confidence=float(probability_maps[row].max()),
                version=bundle.version,
            )
        )
    return facts


def flagged_frames(bundle: PatchHeadBundle, pixels: np.ndarray, patches: np.ndarray) -> list[bool]:
    """Whether the gate flags each sampled frame of one clip."""
    return [fact.label == OBSTRUCTED_LABEL for fact in obstruction_facts(bundle, pixels, patches)]


def bank_obstructed_seconds(
    pending: PendingMeasurements, video: Asset, flagged: Sequence[bool]
) -> None:
    """Bank a video's flagged detector-frame seconds on its own producer.

    No playback is fetched for it, and `choose_window` only avoids the seconds this banks;
    a video never measured for it plays exactly as it did before this head existed.
    """
    times = even_timestamps(video.duration_seconds or 0.0, len(flagged))
    pending.motion_residual(
        asset_id=video.id,
        producer=OBSTRUCTION_FRAME_PRODUCER,
        source_digest=source_metadata_digest(video),
        measured={
            "obstructed_at": list(obstructed_seconds(list(zip(times, flagged, strict=True))))
        },
    )
