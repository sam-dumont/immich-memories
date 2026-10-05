"""The finger-over-the-lens gate: rank-only, and never fooled by a face at the edge (#2022)."""

from __future__ import annotations

import numpy as np

from immich_memories.analysis.editorial_obstruction import (
    PATCH_GRID,
    decide,
    denormalized_crop_bgr,
    obstructed_seconds,
)
from immich_memories.analysis.subject_framing import FaceBox
from immich_memories.triage.preprocess import IMAGENET_MEAN, IMAGENET_STD


def _skin_frame(flagged_cols: slice = slice(0, 4)) -> np.ndarray:
    """A 224x224 BGR frame: skin-toned and bright everywhere a blob will be placed."""
    frame = np.full((224, 224, 3), (90, 140, 210), dtype=np.uint8)  # BGR, warm skin tone
    return frame


def _edge_probability_map(cols: slice = slice(0, 4)) -> np.ndarray:
    """A 16x16 patch probability map with a confident, edge-touching blob."""
    grid = np.zeros((PATCH_GRID, PATCH_GRID), dtype=np.float32)
    grid[:, cols] = 0.9
    return grid


def test_a_confident_skin_toned_edge_blob_is_obstructed():
    reading = decide(_skin_frame(), _edge_probability_map())

    assert reading.obstructed
    assert reading.label == "obstructed"


def test_no_patch_crosses_threshold_reads_clear():
    grid = np.full((PATCH_GRID, PATCH_GRID), 0.2, dtype=np.float32)

    reading = decide(_skin_frame(), grid)

    assert not reading.obstructed


def test_a_blob_that_never_touches_an_edge_is_not_obstructed():
    grid = np.zeros((PATCH_GRID, PATCH_GRID), dtype=np.float32)
    grid[6:10, 6:10] = 0.9  # dead centre, touches no border

    reading = decide(_skin_frame(), grid)

    assert not reading.obstructed


def test_a_small_edge_blob_under_the_area_floor_is_not_obstructed():
    grid = np.zeros((PATCH_GRID, PATCH_GRID), dtype=np.float32)
    grid[0, 0] = 0.9  # one patch: far under the 0.15 area floor

    reading = decide(_skin_frame(), grid)

    assert not reading.obstructed


def test_a_dark_edge_blob_is_not_obstructed():
    """A floor Y < 35 is not a lit finger; it reads as a shadow instead."""
    frame = np.full((224, 224, 3), (5, 10, 15), dtype=np.uint8)

    reading = decide(frame, _edge_probability_map())

    assert not reading.obstructed


def test_a_non_skin_toned_edge_blob_is_not_obstructed():
    frame = np.full((224, 224, 3), (200, 180, 40), dtype=np.uint8)  # saturated blue-ish, BGR

    reading = decide(frame, _edge_probability_map())

    assert not reading.obstructed


def test_face_veto_a_face_at_the_frame_edge_is_not_a_finger():
    face = FaceBox(x1=0.0, y1=0.0, x2=0.3, y2=1.0, named=False)

    reading = decide(_skin_frame(), _edge_probability_map(), faces=(face,))

    assert not reading.obstructed


def test_a_face_elsewhere_in_frame_does_not_veto_an_edge_blob():
    face = FaceBox(x1=0.6, y1=0.6, x2=0.9, y2=0.9, named=False)

    reading = decide(_skin_frame(), _edge_probability_map(), faces=(face,))

    assert reading.obstructed


def test_obstructed_seconds_keeps_only_the_flagged_timestamps():
    frames = [(0.0, False), (0.5, True), (1.0, True), (1.5, False)]

    assert obstructed_seconds(frames) == (0.5, 1.0)


def test_denormalized_crop_round_trips_the_encoders_own_preprocessing():
    rgb = np.full((224, 224, 3), 128, dtype=np.uint8)
    normalized = ((rgb.astype(np.float32) / 255.0 - IMAGENET_MEAN) / IMAGENET_STD).transpose(
        2, 0, 1
    )

    bgr = denormalized_crop_bgr(normalized.astype(np.float32))

    assert bgr.shape == (224, 224, 3)
    assert np.allclose(bgr[0, 0], rgb[0, 0][::-1], atol=2)
