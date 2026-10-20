"""The photo move's frame cut, as kernels: `renderer.cut_frame` on the GPU (#2760).

The same three steps and the same sampling as OpenCV, so a frame lands within a
code value of the CPU's: the blurred fill warped bilinearly into a reduced
canvas and rounded to the picture's depth, that enlarged bilinearly with
half-pixel centres (`cv2.resize`), and the sharp picture warped bilinearly into
the photo window with its edges repeated (`cv2.warpAffine` takes INTER_AREA as
bilinear when it warps). The picture and its fill go up once a still; each
frame comes back once.

Only imported once `gpu_moves` has seen the kernel library run on a GPU.

Note: this module does NOT use 'from __future__ import annotations' because
kernel signatures need actual type objects, not string annotations.
"""

import functools
import threading
from typing import Any

import numpy as np

from immich_memories.photos.renderer import FrameView, KenBurnsLayers
from immich_memories.titles.gpu_kernel_backend import ti

# How each frame is assembled: the fill and the window, black bands, or the
# picture over the whole viewport.
_FILLED, _BANDED, _FULL = 0, 1, 2


@ti.func
def _bilinear(image: ti.template(), x: ti.f32, y: ti.f32, channel: ti.i32) -> ti.f32:
    """A bilinear sample at pixel-centre coordinates, edges repeated."""
    height, width = image.shape[0], image.shape[1]
    left, top = ti.floor(x), ti.floor(y)
    fx, fy = x - left, y - top
    x0 = ti.min(ti.max(ti.cast(left, ti.i32), 0), width - 1)
    x1 = ti.min(ti.max(ti.cast(left, ti.i32) + 1, 0), width - 1)
    y0 = ti.min(ti.max(ti.cast(top, ti.i32), 0), height - 1)
    y1 = ti.min(ti.max(ti.cast(top, ti.i32) + 1, 0), height - 1)
    upper = image[y0, x0, channel] * (1.0 - fx) + image[y0, x1, channel] * fx
    lower = image[y1, x0, channel] * (1.0 - fx) + image[y1, x1, channel] * fx
    return upper * (1.0 - fy) + lower * fy


@ti.kernel
def _warp_fill(
    blur: ti.types.ndarray(dtype=ti.f32, ndim=3),
    reduced: ti.types.ndarray(dtype=ti.f32, ndim=3),
    scale_x: ti.f32,
    offset_x: ti.f32,
    scale_y: ti.f32,
    offset_y: ti.f32,
    top: ti.f32,
):
    for y, x in ti.ndrange(reduced.shape[0], reduced.shape[1]):
        source_x = (x - offset_x) / scale_x
        source_y = (y - offset_y) / scale_y
        for channel in ti.static(range(3)):
            value = _bilinear(blur, source_x, source_y, channel)
            reduced[y, x, channel] = ti.min(ti.max(ti.round(value), 0.0), top)


@ti.func
def _inside(window: ti.template(), x: ti.i32, y: ti.i32) -> ti.i32:
    return (
        x >= window[0]
        and x < window[0] + window[2]
        and y >= window[1]
        and y < window[1] + window[3]
    )


@ti.func
def _sharp_source(
    window: ti.template(), x: ti.i32, y: ti.i32, mode: ti.i32, scale_x: ti.f32,
    offset_x: ti.f32, scale_y: ti.f32, offset_y: ti.f32,
):  # fmt: skip
    """Where a frame pixel samples the picture: window-local unless it fills the frame."""
    local_x, local_y = ti.cast(x, ti.f32), ti.cast(y, ti.f32)
    if mode != _FULL:
        local_x -= window[0]
        local_y -= window[1]
    return (local_x - offset_x) / scale_x, (local_y - offset_y) / scale_y


@functools.cache
def _compose_kernel(depth: Any) -> Any:
    @ti.kernel
    def compose(
        big: ti.types.ndarray(dtype=depth, ndim=3),
        reduced: ti.types.ndarray(dtype=ti.f32, ndim=3),
        frame: ti.types.ndarray(dtype=depth, ndim=3),
        scale_x: ti.f32,
        offset_x: ti.f32,
        scale_y: ti.f32,
        offset_y: ti.f32,
        window: ti.types.ndarray(dtype=ti.i32, ndim=1),
        mode: ti.i32,
        top: ti.f32,
    ):
        height, width = frame.shape[0], frame.shape[1]
        for y, x in ti.ndrange(height, width):
            source_x, source_y = (
                ti.max((x + 0.5) * reduced.shape[1] / width - 0.5, 0.0),
                ti.max((y + 0.5) * reduced.shape[0] / height - 0.5, 0.0),
            )
            sharp = mode == _FULL or _inside(window, x, y)
            if sharp:
                source_x, source_y = _sharp_source(
                    window, x, y, mode, scale_x, offset_x, scale_y, offset_y
                )
            for channel in ti.static(range(3)):
                value = 0.0
                if sharp:
                    value = _bilinear(big, source_x, source_y, channel)
                elif mode == _FILLED:
                    value = _bilinear(reduced, source_x, source_y, channel)
                frame[y, x, channel] = ti.cast(ti.min(ti.max(ti.round(value), 0.0), top), depth)

    return compose


class GpuFrameCutter:
    """One still's layers on the device, and its frames cut from them."""

    def __init__(self, layers: KenBurnsLayers, lock: threading.Lock) -> None:
        self._layers = layers
        self._lock = lock
        big = layers.big
        self._depth = ti.u8 if big.dtype == np.uint8 else ti.u16
        self._top = float(np.iinfo(big.dtype).max)
        vp_w, vp_h = layers.viewport
        bg_w, bg_h = layers.background
        with lock:
            self._big = ti.ndarray(dtype=self._depth, shape=big.shape)
            self._big.from_numpy(np.ascontiguousarray(big))
            self._frame = ti.ndarray(dtype=self._depth, shape=(vp_h, vp_w, 3))
            self._reduced = ti.ndarray(dtype=ti.f32, shape=(bg_h, bg_w, 3))
            self._window = ti.ndarray(dtype=ti.i32, shape=(4,))
            self._window.from_numpy(np.asarray(layers.window, dtype=np.int32))
            self._blur = None
            if layers.blur is not None:
                self._blur = ti.ndarray(dtype=ti.f32, shape=layers.blur.shape)
                self._blur.from_numpy(np.ascontiguousarray(layers.blur, dtype=np.float32))
            self._compose = _compose_kernel(self._depth)

    def cut(self, view: FrameView) -> np.ndarray:
        if view.fills_viewport(self._layers):
            mode = _FULL
        else:
            mode = _FILLED if self._blur is not None and view.blur is not None else _BANDED
        sharp = view.sharp
        with self._lock:
            if mode == _FILLED and view.blur is not None:
                fill = view.blur
                _warp_fill(
                    self._blur, self._reduced, float(fill[0, 0]), float(fill[0, 2]),
                    float(fill[1, 1]), float(fill[1, 2]), self._top,
                )  # fmt: skip
            self._compose(
                self._big, self._reduced, self._frame, float(sharp[0, 0]), float(sharp[0, 2]),
                float(sharp[1, 1]), float(sharp[1, 2]), self._window, mode, self._top,
            )  # fmt: skip
            return self._frame.to_numpy()
