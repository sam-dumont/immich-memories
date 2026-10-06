"""The finger-over-the-lens check: a rank-only warning, never a drop (#2022).

A patch-level head answers *where* a frame's edge is covered by something that is not the
scene: skin-toned, defocused, and touching a border. The gate below turns that probability
map into one yes/no the way a human would read it: a big enough blob, warm enough, lit well
enough, and not simply a person's own face caught near the frame edge.

Measured against a public corpus and the owner's held-out library: it catches roughly half of
real finger-over-lens shots at about 1-in-250 of the library flagged, which is why it ranks a
clean sibling ahead rather than dropping the shot outright. See
`src/immich_memories/triage/bundled_heads/public-obstruction-v1.md` for the training recipe
and its counts.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from immich_memories.analysis.subject_framing import FaceBox

HEAD_NAME = "obstruction"
HEAD_VERSION = "public-obstruction-v1"
WARNING = "OBSTRUCTED (edge)"
CLEAR_LABEL = "clear"
OBSTRUCTED_LABEL = "obstructed"

# The frame this detector was fit against: a 224x224 crop, patches on a 16x16 grid.
CROP_SIZE = 224
PATCH_GRID = 16

# Per-patch probability a patch is part of the obstruction.
PROB_THRESHOLD = 0.5
# Share of the frame the largest edge-touching flagged blob must cover.
AREA_MIN = 0.15
# Share of the blob's interior that reads as skin tone in YCrCb.
SKIN_MIN = 0.5
# The blob must not be a shadow: its mean luma floor.
Y_MIN = 35.0
# A face box covering this much of the flagged blob says "that is a face", not a finger.
FACE_VETO_OVERLAP = 0.5


@dataclass(frozen=True)
class ObstructionReading:
    """What the gate saw in one frame, and the yes/no it decided."""

    area: float
    skin: float
    luma: float
    obstructed: bool

    @property
    def label(self) -> str:
        return OBSTRUCTED_LABEL if self.obstructed else CLEAR_LABEL


def _largest_edge_blob(probability_map: np.ndarray) -> np.ndarray | None:
    """The largest connected patch of ``probability_map`` above threshold that touches a
    border of the patch grid; a finger that does not reach the edge is not one."""
    mask = (probability_map >= PROB_THRESHOLD).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=4)
    best_label, best_area = None, 0
    for index in range(1, count):
        x, y, w, h, area = stats[index]
        touches_edge = 0 in (x, y) or PATCH_GRID in (x + w, y + h)
        if touches_edge and area > best_area:
            best_label, best_area = index, area
    return None if best_label is None else labels == best_label


def _region_stats(image_bgr: np.ndarray, patch_mask: np.ndarray) -> tuple[float, float, float]:
    """Area fraction of the frame, mean skin fraction and mean luma inside the blob."""
    pixel_mask = cv2.resize(
        patch_mask.astype(np.uint8), (CROP_SIZE, CROP_SIZE), interpolation=cv2.INTER_NEAREST
    ).astype(bool)
    ycc = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2YCrCb).astype(np.float32)
    luma, cr, cb = ycc[..., 0][pixel_mask], ycc[..., 1][pixel_mask], ycc[..., 2][pixel_mask]
    skin = ((cr > 133) & (cr < 173) & (cb > 77) & (cb < 127)).mean()
    area = float(patch_mask.sum()) / (PATCH_GRID * PATCH_GRID)
    return area, float(skin), float(luma.mean())


def _overlaps_face(patch_mask: np.ndarray, faces: tuple[FaceBox, ...]) -> bool:
    """A known face covering most of the flagged blob vetoes the flag (#2022 face veto)."""
    if not faces or not patch_mask.any():
        return False
    rows, cols = np.nonzero(patch_mask)
    blob_x1, blob_x2 = cols.min() / PATCH_GRID, (cols.max() + 1) / PATCH_GRID
    blob_y1, blob_y2 = rows.min() / PATCH_GRID, (rows.max() + 1) / PATCH_GRID
    blob_area = patch_mask.sum() / (PATCH_GRID * PATCH_GRID)
    for face in faces:
        overlap_x = max(0.0, min(blob_x2, face.x2) - max(blob_x1, face.x1))
        overlap_y = max(0.0, min(blob_y2, face.y2) - max(blob_y1, face.y1))
        if blob_area > 0 and (overlap_x * overlap_y) / blob_area >= FACE_VETO_OVERLAP:
            return True
    return False


def decide(
    image_bgr: np.ndarray,
    probability_map: np.ndarray,
    *,
    faces: tuple[FaceBox, ...] = (),
) -> ObstructionReading:
    """One frame's reading: a 224x224 BGR crop and its 16x16 per-patch probability map.

    ``faces`` are the frame's known face boxes, normalized 0..1; a flag whose blob mostly
    sits inside one of them is vetoed, since a face at the frame's edge looks exactly like
    a defocused, skin-toned, edge-touching blob to the patch head.
    """
    blob = _largest_edge_blob(probability_map)
    if blob is None:
        return ObstructionReading(area=0.0, skin=0.0, luma=0.0, obstructed=False)
    area, skin, luma = _region_stats(image_bgr, blob)
    obstructed = (
        area >= AREA_MIN and skin >= SKIN_MIN and luma >= Y_MIN and not _overlaps_face(blob, faces)
    )
    return ObstructionReading(area=area, skin=skin, luma=luma, obstructed=obstructed)


def denormalized_crop_bgr(chw_normalized: np.ndarray) -> np.ndarray:
    """Recover the uint8 BGR 224x224 crop the encoder's own preprocessing produced.

    The patch head needs the same crop the encoder saw for its skin/brightness gate; this
    reverses `triage.preprocess.preprocess_image_bytes` instead of decoding the picture a
    second time.
    """
    from immich_memories.triage.preprocess import IMAGENET_MEAN, IMAGENET_STD

    rgb = chw_normalized.transpose(1, 2, 0) * IMAGENET_STD + IMAGENET_MEAN
    rgb = np.clip(rgb * 255.0, 0, 255).astype(np.uint8)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def obstructed_seconds(frames: list[tuple[float, bool]]) -> tuple[float, ...]:
    """The timestamps of a video's sampled detector frames the gate flagged."""
    return tuple(second for second, flagged in frames if flagged)
