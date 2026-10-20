"""Photo moves cut on the GPU land within a code value of the CPU's frames.

Runs where the title kernel library starts on a GPU (CUDA, Metal, Vulkan) and
skips elsewhere: the blur fill around a portrait still, black bands around one,
a landscape still filling the frame, and a 16-bit still.
"""

from __future__ import annotations

import numpy as np
import pytest

from immich_memories.photos import gpu_moves
from immich_memories.photos.renderer import (
    KenBurnsParams,
    ken_burns_frames,
    ken_burns_layers,
    move_frames,
)

pytestmark = pytest.mark.integration

# Captured before the suite pins photo moves to the CPU for every test.
REAL_GPU_CUTTER = gpu_moves.gpu_cutter
PARAMS = KenBurnsParams(
    zoom_start=1.0, zoom_end=1.12, pan_start=(0.3, 0.4), pan_end=(0.6, 0.5), fps=30, duration=0.5
)


@pytest.fixture(scope="module")
def gpu_kernels():
    if gpu_moves._move_kernels() is None:
        pytest.skip("the kernel library does not run on a GPU here")


def _picture(shape, dtype) -> np.ndarray:
    import cv2

    top = np.iinfo(dtype).max
    coarse = (np.random.default_rng(2760).random((48, 36, 3)) * top).astype(dtype)
    return np.ascontiguousarray(
        cv2.resize(coarse, (shape[1], shape[0]), interpolation=cv2.INTER_CUBIC)
    )


@pytest.mark.parametrize(
    ("shape", "dtype", "scale_mode"),
    [
        ((2016, 1512, 3), np.uint8, "blur"),
        ((2016, 1512, 3), np.uint8, "fit"),
        ((1512, 2688, 3), np.uint8, "blur"),
        ((2016, 1512, 3), np.uint16, "blur"),
    ],
)
def test_gpu_frames_match_the_cpus(gpu_kernels, monkeypatch, shape, dtype, scale_mode):
    # WHY: the switch under comparison; OpenCV is what every move got before.
    monkeypatch.setattr(gpu_moves, "gpu_cutter", REAL_GPU_CUTTER)
    layers = ken_burns_layers(_picture(shape, dtype), 1920, 1080, PARAMS, scale_mode=scale_mode)
    code = 1 if dtype == np.uint8 else 257

    pairs = zip(move_frames(layers, PARAMS), ken_burns_frames(layers, PARAMS), strict=True)
    for gpu, cpu in pairs:
        difference = np.abs(gpu.astype(np.int32) - cpu.astype(np.int32))
        assert gpu.dtype == cpu.dtype
        assert difference.max() <= code
        assert difference.mean() < 0.1 * code
