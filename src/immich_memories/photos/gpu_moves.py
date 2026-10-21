"""Whether a photo move's frames are cut on the GPU, and the cutter that does it.

A move warps the resampled picture, warps and enlarges its blurred fill and
places the one in the other, every frame: 61 to 136 ms of CPU a 4K frame on the
render worker, 19 to 25 ms on an M-series Mac. The title kernel library runs the
same warps on CUDA or Metal for the cost of bringing the frame back (#2760).

Nothing here loads that library until its probe has said it can run: a
processor without AVX dies inside the load (#910). A machine whose kernels only
run on the CPU keeps OpenCV, which is quicker there.

Stills are prepared on several threads, and on CUDA the library only works from
the thread that started it: every device call of a move goes to the kernel
thread (`titles.kernel_thread`). Before that, each still on the worker failed to
allocate with CUDA_ERROR_INVALID_CONTEXT and was cut on the CPU (#2785).
"""

from __future__ import annotations

import functools
import logging
import platform
from types import ModuleType
from typing import TYPE_CHECKING, Protocol

import numpy as np

from immich_memories.titles.kernel_thread import on_kernel_thread, release_on_kernel_thread

if TYPE_CHECKING:
    from immich_memories.photos.renderer import FrameView, KenBurnsLayers

logger = logging.getLogger(__name__)

_GPU_BACKENDS = frozenset({"Metal", "CUDA", "Vulkan"})
_DEPTHS = (np.dtype(np.uint8), np.dtype(np.uint16))


class FrameCutter(Protocol):
    def cut(self, view: FrameView) -> np.ndarray: ...

    def close(self) -> None: ...


class _DeviceCutter(Protocol):
    def cut(self, view: FrameView) -> np.ndarray: ...

    def release(self) -> None: ...


@functools.cache
def _move_kernels() -> ModuleType | None:
    """The move kernels, once the probe has seen the kernel library run on a GPU here."""
    from immich_memories.titles.kernel_backend_probe import gpu_backend, kernel_dispatch_failure

    if kernel_dispatch_failure() is not None or gpu_backend(platform.system())[0] is None:
        return None
    from immich_memories.photos import move_kernels

    return move_kernels


@functools.cache
def _note_gpu(backend: str) -> None:
    logger.info("Photo moves are cut on the GPU (%s)", backend)


def _device_cutter(kernels: ModuleType, layers: KenBurnsLayers) -> _DeviceCutter | None:
    """On the kernel thread: start the runtime if it is not running and upload the still.

    Started here rather than once: an idle worker resets the runtime between
    jobs (`release_kernels`), and the next still starts it again.
    """
    from immich_memories.titles.kernels import init_kernels

    backend = init_kernels()
    if backend not in _GPU_BACKENDS:
        return None
    failure = None
    try:
        cutter: _DeviceCutter = kernels.GpuFrameCutter(layers)
    except Exception as exc:  # noqa: BLE001 — reported below, without its traceback
        failure = f"{type(exc).__name__}: {exc}"
    if failure is not None:
        # WHY raised out here: the original's traceback holds the half-built cutter,
        # and the thread that drops the exception would free its buffers.
        raise RuntimeError(failure)
    _note_gpu(backend)
    return cutter


class KernelThreadCutter:
    """A still on the device, cut from whichever thread prepares it."""

    def __init__(self, device: _DeviceCutter) -> None:
        self._device: _DeviceCutter | None = device

    def cut(self, view: FrameView) -> np.ndarray:
        if self._device is None:
            raise RuntimeError("the still's device buffers were released")
        return on_kernel_thread(self._device.cut, view)

    def close(self) -> None:
        """Free the device buffers on the kernel thread, and wait for it."""
        device, self._device = self._device, None
        if device is not None:
            on_kernel_thread(device.release)

    def __del__(self) -> None:
        # A cutter dropped unclosed must not free its buffers on this thread.
        device, self._device = self._device, None
        if device is not None:
            release_on_kernel_thread(device.release)


def gpu_cutter(layers: KenBurnsLayers) -> FrameCutter | None:
    """A GPU cutter for this still's frames, or None to cut them with OpenCV."""
    big = layers.big
    if big.dtype not in _DEPTHS or big.ndim != 3 or big.shape[2] != 3:
        return None
    try:
        kernels = _move_kernels()
        if kernels is None:
            return None
        device = on_kernel_thread(_device_cutter, kernels, layers)
    except Exception as exc:  # noqa: BLE001 — any device failure leaves the still to OpenCV
        logger.warning("Photo move on the CPU, the GPU could not take the still: %s", exc)
        return None
    return None if device is None else KernelThreadCutter(device)
