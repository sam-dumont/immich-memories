"""Motion-interpolated in-between frames for the opening title (#2389)."""

from __future__ import annotations

import cv2
import numpy as np

from immich_memories.titles.motion_interpolation import build_flow_interpolator

WIDTH, HEIGHT, SPEED = 320, 180, 12
TEXTURE_WIDTH = WIDTH + 10 * SPEED


def _texture(seed: int) -> np.ndarray:
    noise = np.random.default_rng(seed).uniform(0, 255, (HEIGHT, TEXTURE_WIDTH, 3))
    texture = cv2.GaussianBlur(noise.astype(np.float32), (0, 0), 3)
    return cv2.normalize(texture, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)


def _pan(count: int, seed: int = 1, start: int = 0) -> list[np.ndarray]:
    texture = _texture(seed)
    return [
        np.ascontiguousarray(texture[:, x : x + WIDTH])
        for x in range(start * SPEED, (start + count) * SPEED, SPEED)
    ]


def _seen_at(position: float) -> np.ndarray:
    """What a camera really that far along the pan would have seen."""
    matrix = np.float32([[1, 0, -position * SPEED], [0, 1, 0]])
    return cv2.warpAffine(_texture(1).astype(np.float32), matrix, (WIDTH, HEIGHT)) / 255.0


def test_an_in_between_frame_is_the_pan_moved_part_way_not_a_double_exposure() -> None:
    frames = _pan(8)
    interpolator = build_flow_interpolator(frames, warps_needed=4)
    assert interpolator is not None

    truth = _seen_at(3.5)
    inner = (slice(20, -20), slice(40, -40))
    warped = interpolator.frame_at(3.5)[inner]
    blended = (0.5 * (frames[3].astype(np.float32) + frames[4]) / 255.0)[inner]

    warped_error = np.abs(warped - truth[inner]).mean()
    assert warped_error < 0.02
    assert warped_error < 0.3 * np.abs(blended - truth[inner]).mean()


def test_whole_positions_return_the_source_frame_in_its_own_transfer() -> None:
    frames = [(frame.astype(np.uint16) * 257) for frame in _pan(6)]
    interpolator = build_flow_interpolator(frames, warps_needed=4)
    assert interpolator is not None

    frame = interpolator.frame_at(2.0)

    assert frame.dtype == np.float32
    np.testing.assert_allclose(frame, frames[2] / 65535.0, atol=1e-6)


def test_a_scene_cut_in_the_source_is_not_warped_across() -> None:
    frames = _pan(4, seed=1) + _pan(4, seed=2, start=4)

    assert build_flow_interpolator(frames, warps_needed=4) is None


def test_work_over_the_budget_is_refused() -> None:
    assert build_flow_interpolator(_pan(6), warps_needed=30, budget_seconds=0.0) is None
