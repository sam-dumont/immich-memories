"""Bank the finger-over-the-lens reading for every preview, on the same encoder (#2022).

A rank-only head: a picture never measured for it, or whose preview could not be read,
renders exactly as it did before this head existed (no warning, no change in order).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import numpy as np
from PIL import UnidentifiedImageError

from immich_memories.analysis.editorial_bound_sample import source_metadata_digest
from immich_memories.analysis.editorial_obstruction import (
    decide,
    denormalized_crop_bgr,
    obstructed_seconds,
)
from immich_memories.analysis.subject_framing import FaceBox
from immich_memories.api.models import Asset
from immich_memories.cache.embedding_cache import HeadFactStore, PendingHeadFacts
from immich_memories.db import Store
from immich_memories.processing.frame_sampling import even_timestamps
from immich_memories.store.cut_measurements import PendingMeasurements
from immich_memories.triage.encoder import DinoEncoder
from immich_memories.triage.heads import HeadFact, PatchHeadBundle
from immich_memories.triage.preprocess import preprocess_image_bytes

BATCH_PICTURES = 32
# #2022: the method string a `motion_residuals` producer key names; FRAME_WIDTH=768 is
# `editorial_preparation_detector_frames.FRAME_WIDTH`, the frames this reuses rather than
# re-sampling. The timestamps are reconstructed with the same even spacing the detector
# frame sampler uses, since the sampler itself does not carry its chosen seconds forward.
OBSTRUCTION_FRAME_PRODUCER = "edge-obstruction-v1@detector-frames-768"


def prepare_obstruction_heads(
    *,
    asset_ids: Sequence[str],
    store: Store,
    bundle_path: Path,
    encoder_path: Path,
    preview_for: Callable[[str], bytes],
    faces_for: Callable[[str], Sequence[FaceBox]] | None = None,
    check_cancelled: Callable[[], None],
    progress: Callable[[str, int, int], None],
    provider: str = "auto",
    open_encoder: Callable[..., DinoEncoder] = DinoEncoder.open,
) -> dict[str, str]:
    """Decide and bank the obstruction head for each asset not already banked for it.

    Returns the assets whose preview could not be read, with why; a clip's or a picture's
    line is unaffected either way, since the warning this head produces is add-only.
    """
    bundle = PatchHeadBundle.load(bundle_path)
    if not encoder_path.is_file():
        raise FileNotFoundError(
            f"the obstruction head needs the pinned DINOv2 ONNX export at {encoder_path}. "
            "Run `immich-memories models fetch` to download it."
        )
    check_cancelled()
    encoder = open_encoder(encoder_path, provider=provider)
    if bundle.encoder_key != encoder.key:
        raise ValueError("obstruction head bundle was trained on another encoder")
    head_store = HeadFactStore(store)
    banked = head_store.facts_for(asset_ids, head=bundle.name, version=bundle.version)
    pending_ids = [asset_id for asset_id in asset_ids if asset_id not in banked]
    faces_for = faces_for or (lambda _asset_id: ())
    failures: dict[str, str] = {}
    with PendingHeadFacts(head_store) as bank:
        for start in range(0, len(pending_ids), BATCH_PICTURES):
            check_cancelled()
            chunk = pending_ids[start : start + BATCH_PICTURES]
            _decide_chunk(chunk, bundle, encoder, preview_for, faces_for, bank, failures)
            progress("obstruction", min(start + BATCH_PICTURES, len(pending_ids)), len(pending_ids))
    return failures


def _decide_chunk(
    chunk: Sequence[str],
    bundle: PatchHeadBundle,
    encoder: DinoEncoder,
    preview_for: Callable[[str], bytes],
    faces_for: Callable[[str], Sequence[FaceBox]],
    bank: PendingHeadFacts,
    failures: dict[str, str],
) -> None:
    pixels: list[np.ndarray] = []
    kept: list[str] = []
    for asset_id in chunk:
        try:
            pixels.append(preprocess_image_bytes(preview_for(asset_id)))
            kept.append(asset_id)
        except (OSError, ValueError, UnidentifiedImageError) as exc:
            failures[asset_id] = f"{type(exc).__name__}: {exc}"
    if not kept:
        return
    _, patches = encoder.embed_with_patches(np.stack(pixels))
    probability_maps = bundle.patch_probabilities(patches)
    for row, asset_id in enumerate(kept):
        image_bgr = denormalized_crop_bgr(pixels[row])
        reading = decide(image_bgr, probability_maps[row], faces=tuple(faces_for(asset_id)))
        fact = HeadFact(
            head=bundle.name,
            label=reading.label,
            confidence=float(probability_maps[row].max()),
            version=bundle.version,
        )
        bank.add(asset_id, [fact], encoder_key=encoder.key)


def prepare_obstruction_frames(
    *,
    store: Store,
    videos: Mapping[str, Asset],
    frame_paths: Mapping[str, Sequence[Path]],
    bundle_path: Path,
    encoder_path: Path,
    check_cancelled: Callable[[], None],
    progress: Callable[[str, int, int], None] | None = None,
    provider: str = "auto",
    open_encoder: Callable[..., DinoEncoder] = DinoEncoder.open,
) -> dict[str, str]:
    """Bank each video's flagged detector-frame seconds, read off the frames
    `editorial_preparation_detector_frames.DetectorFrames` already sampled for the exposure
    head. No playback is fetched for it, and `choose_window` only avoids the seconds this
    banks; a video never measured for it plays exactly as it did before this head existed.
    """
    report = progress or (lambda *_args: None)
    report("obstruction_frames", 0, len(frame_paths))
    bundle = PatchHeadBundle.load(bundle_path)
    if not encoder_path.is_file():
        raise FileNotFoundError(
            f"the obstruction head needs the pinned DINOv2 ONNX export at {encoder_path}. "
            "Run `immich-memories models fetch` to download it."
        )
    check_cancelled()
    encoder = open_encoder(encoder_path, provider=provider)
    if bundle.encoder_key != encoder.key:
        raise ValueError("obstruction head bundle was trained on another encoder")
    failures: dict[str, str] = {}
    with PendingMeasurements(store) as pending:
        for index, (asset_id, paths) in enumerate(frame_paths.items(), 1):
            check_cancelled()
            _bank_video_frames(asset_id, paths, videos, bundle, encoder, pending, failures)
            pending.flush()
            report("obstruction_frames", index, len(frame_paths))
    return failures


def _bank_video_frames(
    asset_id: str,
    paths: Sequence[Path],
    videos: Mapping[str, Asset],
    bundle: PatchHeadBundle,
    encoder: DinoEncoder,
    pending: PendingMeasurements,
    failures: dict[str, str],
) -> None:
    try:
        pixels = [preprocess_image_bytes(Path(path).read_bytes()) for path in paths]
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        failures[asset_id] = f"{type(exc).__name__}: {exc}"
        return
    _, patches = encoder.embed_with_patches(np.stack(pixels))
    probability_maps = bundle.patch_probabilities(patches)
    times = even_timestamps(videos[asset_id].duration_seconds or 0.0, len(paths))
    flagged = [
        decide(denormalized_crop_bgr(pixels[index]), probability_maps[index]).obstructed
        for index in range(len(paths))
    ]
    pending.motion_residual(
        asset_id=asset_id,
        producer=OBSTRUCTION_FRAME_PRODUCER,
        source_digest=source_metadata_digest(videos[asset_id]),
        measured={
            "obstructed_at": list(obstructed_seconds(list(zip(times, flagged, strict=True))))
        },
    )
