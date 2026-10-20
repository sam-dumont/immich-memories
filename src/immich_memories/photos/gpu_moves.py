"""Whether a photo move's frames are cut on the GPU, and the cutter that does it.

A move warps the resampled picture, warps and enlarges its blurred fill and
places the one in the other, every frame: 61 to 136 ms of CPU a 4K frame on the
render worker, 19 to 25 ms on an M-series Mac. The title kernel library runs the
same warps on CUDA or Metal for the cost of bringing the frame back (#2760).

Nothing here loads that library until its probe has said it can run: a
processor without AVX dies inside the load (#910). A machine whose kernels only
run on the CPU keeps OpenCV, which is quicker there.
"""

from __future__ import annotations

import functools
import logging
import platform
import threading
from types import ModuleType
from typing import TYPE_CHECKING, Protocol

import numpy as np

if TYPE_CHECKING:
    from immich_memories.photos.renderer import FrameView, KenBurnsLayers

logger = logging.getLogger(__name__)

_GPU_BACKENDS = frozenset({"Metal", "CUDA", "Vulkan"})
_DEPTHS = (np.dtype(np.uint8), np.dtype(np.uint16))
# The kernel runtime is not safe to drive from two threads, and stills are
# prepared on several: one move at a time touches the device.
KERNEL_LOCK = threading.Lock()


class FrameCutter(Protocol):
    def cut(self, view: FrameView) -> np.ndarray: ...


@functools.cache
def _move_kernels() -> ModuleType | None:
    from immich_memories.titles.kernel_backend_probe import gpu_backend, kernel_dispatch_failure

    if kernel_dispatch_failure() is not None or gpu_backend(platform.system())[0] is None:
        return None
    from immich_memories.titles.kernels import init_kernels

    with KERNEL_LOCK:
        backend = init_kernels()
    if backend not in _GPU_BACKENDS:
        return None
    from immich_memories.photos import move_kernels

    logger.info("Photo moves are cut on the GPU (%s)", backend)
    return move_kernels


def gpu_cutter(layers: KenBurnsLayers) -> FrameCutter | None:
    """A GPU cutter for this still's frames, or None to cut them with OpenCV."""
    big = layers.big
    if big.dtype not in _DEPTHS or big.ndim != 3 or big.shape[2] != 3:
        return None
    try:
        kernels = _move_kernels()
        if kernels is None:
            return None
        cutter: FrameCutter = kernels.GpuFrameCutter(layers, KERNEL_LOCK)
    except (RuntimeError, OSError) as exc:
        logger.warning("Photo moves stay on the CPU: %s", exc)
        return None
    return cutter
