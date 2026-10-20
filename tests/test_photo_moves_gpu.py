"""A photo move is cut on the GPU when the kernel library runs on one, on the CPU otherwise.

The GPU cuts the same views the CPU would, and a GPU that fails part-way hands
the rest of the move to the CPU without a gap or a repeated frame.
"""

from __future__ import annotations

import numpy as np
import pytest

from immich_memories.photos import gpu_moves
from immich_memories.photos.renderer import (
    KenBurnsParams,
    cut_frame,
    ken_burns_frames,
    ken_burns_layers,
    move_frames,
)

# Captured before the suite pins photo moves to the CPU for every test.
REAL_GPU_CUTTER = gpu_moves.gpu_cutter
PARAMS = KenBurnsParams(
    zoom_start=1.0, zoom_end=1.15, pan_start=(0.2, 0.4), pan_end=(0.7, 0.5), fps=10, duration=1.0
)


def _layers(scale_mode: str = "blur", shape=(300, 200, 3)):
    rng = np.random.default_rng(2760)
    picture = (rng.random(shape) * 255).astype(np.uint8)
    return ken_burns_layers(picture, 320, 180, PARAMS, scale_mode=scale_mode)


class _Cutter:
    """Stands in for the device: cuts on the CPU and counts, or fails from a given frame."""

    def __init__(self, layers, fail_from: int | None = None) -> None:
        self.layers, self.fail_from, self.cuts = layers, fail_from, 0

    def cut(self, view):
        if self.fail_from is not None and self.cuts >= self.fail_from:
            raise RuntimeError("device lost")
        self.cuts += 1
        frame = cut_frame(self.layers, view)
        frame[0, 0, 0] = 7  # marks a frame as the cutter's
        return frame


@pytest.mark.parametrize("scale_mode", ["blur", "fit"])
def test_without_gpu_kernels_the_move_is_cut_on_the_cpu(scale_mode):
    layers = _layers(scale_mode)

    frames = list(move_frames(layers, PARAMS))
    expected = list(ken_burns_frames(layers, PARAMS))

    assert len(frames) == len(expected) == 10
    for frame, reference in zip(frames, expected, strict=True):
        np.testing.assert_array_equal(frame, reference)


def test_a_gpu_cuts_every_frame_when_kernels_run(monkeypatch):
    layers = _layers()
    cutter = _Cutter(layers)
    # WHY: replaces the kernel library's device, which CI runners do not have.
    monkeypatch.setattr(gpu_moves, "gpu_cutter", lambda _layers: cutter)

    frames = list(move_frames(layers, PARAMS))

    assert cutter.cuts == 10
    assert all(frame[0, 0, 0] == 7 for frame in frames)


def test_a_gpu_failing_part_way_hands_the_rest_to_the_cpu(monkeypatch):
    layers = _layers()
    cutter = _Cutter(layers, fail_from=4)
    # WHY: replaces the kernel library's device, which CI runners do not have.
    monkeypatch.setattr(gpu_moves, "gpu_cutter", lambda _layers: cutter)

    frames = list(move_frames(layers, PARAMS))
    expected = list(ken_burns_frames(layers, PARAMS))

    assert len(frames) == 10
    assert [frame[0, 0, 0] == 7 for frame in frames] == [True] * 4 + [False] * 6
    for frame, reference in zip(frames[4:], expected[4:], strict=True):
        np.testing.assert_array_equal(frame, reference)


def test_a_float_picture_is_not_given_to_the_gpu():
    layers = _layers()
    layers = type(layers)(**{**layers.__dict__, "big": layers.big.astype(np.float32)})

    assert REAL_GPU_CUTTER(layers) is None
