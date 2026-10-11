"""Motion-interpolated in-between frames for the opening title's slow motion.

The opening deblurs into its first clip in slow motion, so most of its frames
fall between two source frames. Blending those two is a double exposure, not a
picture halfway between them: a pan slowed to a third held for two frames and
jumped on the third as soon as the blur lifted (#2389). This module moves the
pixels instead. Dense optical flow is measured on a small grey copy of each
pair of neighbouring frames, and both frames are warped part of the way along
it and mixed.

It refuses work it would do badly or slowly: a source whose motion the flow
cannot explain (a scene cut, a whip pan) or a projected cost over the budget
returns None, and the caller plays the source at its own speed instead.
"""

from __future__ import annotations

import logging
import time

import cv2
import numpy as np

logger = logging.getLogger(__name__)

#: Width the flow is measured at. The deblur's sharp end is the only place the
#: warp shows, and flow from a 480 px copy upscaled is well inside a pixel of a
#: full-resolution one on camera motion, at a tenth of the cost.
_FLOW_WIDTH = 480

#: The flow check: each frame, pulled back along the flow measured to it, must
#: land on the frame before. Within this mean error (0-1 scale) the flow is
#: trusted outright; at that size it is mostly compression noise. Measured on a
#: real 12 px-a-frame pan at 1080p: 0.022, against 0.058 with no warp at all.
_RESIDUAL_FLOOR = 0.03
#: Above the floor the warp must still explain most of the change, or the flow
#: is not describing the motion (a scene cut, an occlusion, a flash). A cut
#: measured 0.064 warped against 0.088 unwarped.
_RESIDUAL_SHARE = 0.6

#: Seconds a title may spend on flow and warps before the real-speed reveal is
#: the better trade. A 4K opening measured 0.25 s of flow and 30 warps at 72 ms
#: on one Apple core; a two-core NAS is roughly three times slower.
BUDGET_SECONDS = 10.0


def _as_unit_float(frame: np.ndarray) -> np.ndarray:
    scale = 65535.0 if frame.dtype == np.uint16 else 255.0
    return frame.astype(np.float32) / scale


class FlowInterpolator:
    """Frames at fractional positions between decoded source frames.

    Positions on a whole frame return that frame untouched; between frames,
    both neighbours are warped towards the position along the measured flow and
    mixed by distance. Pixel values are resampled in the source's own transfer,
    so HDR stays HDR.
    """

    def __init__(
        self,
        frames: list[np.ndarray],
        forward: list[np.ndarray],
        backward: list[np.ndarray],
        flow_scale: float,
    ) -> None:
        self._frames = frames
        self._forward = forward
        self._backward = backward
        self._flow_scale = flow_scale
        height, width = frames[0].shape[:2]
        self._size = (width, height)
        grid_y, grid_x = np.mgrid[0:height, 0:width].astype(np.float32)
        self._grid = (grid_x, grid_y)
        self._float_cache: dict[int, np.ndarray] = {}

    def frame_at(self, position: float) -> np.ndarray:
        """The picture at `position` source frames in, float32 on a 0-1 scale."""
        last = len(self._frames) - 1
        position = min(max(position, 0.0), float(last))
        index = min(int(position), last - 1)
        t = position - index
        if t < 1e-3:
            return self._unit(index)
        if t > 1.0 - 1e-3:
            return self._unit(index + 1)
        f01, f10 = self._forward[index], self._backward[index]
        # Flow from the in-between instant back to each neighbour, assuming
        # motion is locally straight across one frame interval.
        to_first = -(1.0 - t) * t * f01 + t * t * f10
        to_second = (1.0 - t) ** 2 * f01 - t * (1.0 - t) * f10
        first = self._warp(self._unit(index), to_first)
        second = self._warp(self._unit(index + 1), to_second)
        return np.clip((1.0 - t) * first + t * second, 0.0, 1.0)

    def _warp(self, frame: np.ndarray, small_flow: np.ndarray) -> np.ndarray:
        flow = np.asarray(
            cv2.resize(small_flow * self._flow_scale, self._size, interpolation=cv2.INTER_LINEAR)
        )
        grid_x, grid_y = self._grid
        return cv2.remap(
            frame,
            grid_x + flow[..., 0],
            grid_y + flow[..., 1],
            cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )

    def _unit(self, index: int) -> np.ndarray:
        cached = self._float_cache.get(index)
        if cached is None:
            cached = _as_unit_float(self._frames[index])
            self._float_cache[index] = cached
            while len(self._float_cache) > 3:
                del self._float_cache[min(self._float_cache)]
        return cached


def _small_grey(frame: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    small = cv2.resize(_as_unit_float(frame), size, interpolation=cv2.INTER_AREA)
    return np.round(cv2.cvtColor(small, cv2.COLOR_RGB2GRAY) * 255.0).astype(np.uint8)


def _measure(flow: cv2.DISOpticalFlow, first: np.ndarray, second: np.ndarray) -> np.ndarray:
    """Dense flow from `first` to `second`, in pixels at their size."""
    out = np.zeros((*first.shape, 2), dtype=np.float32)
    return np.asarray(flow.calc(first, second, out))


def _residuals(first: np.ndarray, second: np.ndarray, flow: np.ndarray) -> tuple[float, float]:
    """How far `second` misses `first` pulled back along `flow`, and with no warp."""
    a = first.astype(np.float32) / 255.0
    b = second.astype(np.float32) / 255.0
    height, width = a.shape
    grid_y, grid_x = np.mgrid[0:height, 0:width].astype(np.float32)
    pulled = cv2.remap(
        b,
        grid_x + flow[..., 0],
        grid_y + flow[..., 1],
        cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )
    # The frame's edge brings in picture the flow cannot know about.
    inner = (slice(16, -16), slice(16, -16))
    return float(np.abs(pulled - a)[inner].mean()), float(np.abs(b - a)[inner].mean())


def _flow_explains_motion(greys: list[np.ndarray], forward: list[np.ndarray]) -> bool:
    for index, flow in enumerate(forward):
        warped, unwarped = _residuals(greys[index], greys[index + 1], flow)
        if warped > _RESIDUAL_FLOOR and warped > _RESIDUAL_SHARE * unwarped:
            logger.info(
                "Title slow motion: flow misses frame %d by %.3f (%.3f unwarped); "
                "playing the reveal at real speed",
                index + 1,
                warped,
                unwarped,
            )
            return False
    return True


def build_flow_interpolator(
    frames: list[np.ndarray], warps_needed: int, budget_seconds: float | None = None
) -> FlowInterpolator | None:
    """A FlowInterpolator for `frames`, or None when it would look wrong or run too long.

    `warps_needed` is how many in-between frames the caller will ask for; the
    projected cost is the flow already measured plus that many timed warps.
    """
    if len(frames) < 2:
        return None
    started = time.perf_counter()
    try:
        height, width = frames[0].shape[:2]
        flow_width = min(_FLOW_WIDTH, width)
        flow_size = (flow_width, max(8, round(height * flow_width / width)))
        greys = [_small_grey(frame, flow_size) for frame in frames]
        flow = cv2.DISOpticalFlow.create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
        forward = [_measure(flow, greys[i], greys[i + 1]) for i in range(len(greys) - 1)]
        if not _flow_explains_motion(greys, forward):
            return None
        backward = [_measure(flow, greys[i + 1], greys[i]) for i in range(len(greys) - 1)]
        interpolator = FlowInterpolator(frames, forward, backward, width / flow_width)
        warp_started = time.perf_counter()
        interpolator.frame_at(0.5)
        warp_seconds = time.perf_counter() - warp_started
    except cv2.error as e:
        logger.warning("Title slow motion: optical flow failed (%s); playing at real speed", e)
        return None
    projected = (warp_started - started) + warp_seconds * warps_needed
    if budget_seconds is None:
        budget_seconds = BUDGET_SECONDS
    if projected > budget_seconds:
        logger.info(
            "Title slow motion: interpolating would take about %.1fs (budget %.1fs); "
            "playing the reveal at real speed",
            projected,
            budget_seconds,
        )
        return None
    logger.info(
        "Title slow motion: motion-interpolated, about %.1fs for %d in-between frames",
        projected,
        warps_needed,
    )
    return interpolator
