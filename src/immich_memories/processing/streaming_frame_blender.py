"""Composing decoded frames into the output stream.

Kept apart from the assembler because none of it runs FFmpeg: it takes frame
iterators and a sink, owns the crossfade scratch buffer, and keeps the frame
count, progress reporting and preview throttling that the assembler used to
thread through argument lists.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from typing import Protocol

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def blend_crossfade(
    frame_a: np.ndarray,
    frame_b: np.ndarray,
    alpha: float,
    out: np.ndarray,
) -> None:
    """In-place crossfade blend: alpha=0 → frame_a, alpha=1 → frame_b.

    WHY cv2 rather than numpy: the three-pass numpy version measured 37.5 ms a
    frame at 4K against 3.5 ms here, and its `casting="unsafe"` truncated every
    element toward zero -- up to 1.6 levels of error where rounding costs 0.5.
    addWeighted also writes straight into `out`, so the second scratch buffer
    the numpy path needed (another 25 MB at 4K) is gone.
    """
    cv2.addWeighted(frame_a, 1.0 - alpha, frame_b, alpha, 0.0, dst=out)


class FrameSink(Protocol):
    """The encoder end of the pipe, as the blender needs to see it."""

    def write_frame(self, frame: np.ndarray) -> None: ...


def _alloc_blend_buf(width: int, height: int, is_hdr: bool, planar_sdr: bool) -> np.ndarray:
    """Allocate the blend destination. One buffer: cv2 writes straight into it."""
    if planar_sdr:
        return np.zeros(width * height * 3 // 2, dtype=np.uint8)
    if is_hdr:
        # WHY: yuv420p10le is flat uint16 — W*H*3 bytes = W*H*3/2 uint16 samples
        return np.zeros(width * height * 3 // 2, dtype=np.uint16)
    return np.zeros((height, width, 3), dtype=np.uint8)


def _match_blend_bufs(
    ref: np.ndarray, blend_buf: np.ndarray, semi_planar: bool = False
) -> tuple[np.ndarray, np.ndarray]:
    """Create black frame and ensure blend buffers match actual frame shape.

    WHY: HDR mode pre-allocates flat uint16 YUV buffers, but some clips
    (title screens, FFmpeg filter fallback on Linux) may decode as 3D RGB.
    """
    black = np.zeros_like(ref)
    # WHY: in YUV, all-zeros = GREEN (U=0, V=0 = green chroma).
    # For flat uint16 arrays (yuv420p10le), set chroma planes to 512.
    if ref.ndim == 1 and ref.dtype == np.uint16:
        # Y plane occupies first 2/3 of the flat array, U+V the last 1/3
        y_size = len(ref) * 2 // 3
        # P010 keeps its 10 bits at the top of each sample.
        black[y_size:] = 512 << 6 if semi_planar else 512
    if ref.ndim == 1 and ref.dtype == np.uint8:
        # Planar 8-bit: limited-range black is Y=16, U=V=128.
        y_size = len(ref) * 2 // 3
        black[:y_size] = 16
        black[y_size:] = 128
    if blend_buf.shape != ref.shape or blend_buf.dtype != ref.dtype:
        blend_buf = np.zeros_like(ref)
    return black, blend_buf


def _hold_or_fallback(
    frame: np.ndarray | None,
    last: np.ndarray | None,
    black: np.ndarray,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Return frame (or held last frame) and update last-seen cache."""
    if frame is not None:
        return frame, frame
    return (last if last is not None else black), last


def _next_frame(frames: Iterator[np.ndarray]) -> tuple[np.ndarray | None, str | None]:
    """The next frame, or None and what the clip's decoder said about ending (#2792)."""
    try:
        return next(frames), None
    except StopIteration as end:
        return None, end.value


def _with_why(text: str, why: str | None) -> str:
    return f"{text}; {why}" if why else text


def _log_short_fade(missing: dict[str, int], said: dict[str, str | None], fade_frames: int) -> None:
    """One warning for a fade where either clip ran out of frames."""
    sides = [
        _with_why(f"the {side} clip gave no frame for {count} of {fade_frames}", said[side])
        for side, count in missing.items()
        if count
    ]
    if sides:
        logger.warning("Fade ran short: %s; its last frame, or black, stood in", "; ".join(sides))


class FrameBlender:
    """Feed decoded frames to a sink, crossfading across clip boundaries."""

    def __init__(
        self,
        sink: FrameSink,
        width: int,
        height: int,
        is_hdr: bool = False,
        planar_sdr: bool = False,
        semi_planar: bool = False,
        total_frames: int = 0,
        report_interval: int = 1,
        progress_callback: Callable[[int, int], None] | None = None,
        frame_preview_callback: Callable[[bytes], None] | None = None,
    ) -> None:
        self._sink = sink
        self._width = width
        self._height = height
        self._is_hdr = is_hdr
        # 10-bit frames arrive as P010 rather than planar yuv420p10le.
        self._semi_planar = semi_planar
        self._total_frames = total_frames
        self._report_interval = report_interval
        self._progress_callback = progress_callback
        self._frame_preview_callback = frame_preview_callback
        self._blend_buf = _alloc_blend_buf(width, height, is_hdr, planar_sdr)
        self._frames_written = 0
        # The frame an underrun holds: still intact, since frames are written synchronously.
        self._last_written: np.ndarray | None = None
        self._last_preview_time = 0.0

    @property
    def frames_written(self) -> int:
        """Frames handed to the sink so far, crossfade frames included."""
        return self._frames_written

    def emit_body(self, active_iter: Iterator[np.ndarray], count: int, clip: str = "") -> None:
        """Write `count` frames from one clip straight through to the sink.

        A clip that runs out early is held on the last frame written until its
        planned length is met: a frame short here is a frame short for the whole
        film, and the music, captions and every later clip would drift (#2785).
        """
        for emitted in range(max(count, 0)):
            frame, why = _next_frame(active_iter)
            if frame is None:
                self._hold_last(
                    count - emitted, _with_why(f"expected {count} frames, got {emitted}", why), clip
                )
                return
            self._write(frame)

    def emit_crossfade(
        self,
        active_iter: Iterator[np.ndarray],
        next_iter: Iterator[np.ndarray],
        fade_frames: int,
    ) -> None:
        """Blend `fade_frames` from two clips and write the result to the sink.

        A side that runs out is held on its last frame, or black if it gave none,
        and the fade says so once (#2792).
        """
        blend_buf = self._blend_buf
        black: np.ndarray | None = None
        last_a: np.ndarray | None = None
        last_b: np.ndarray | None = None
        missing = {"outgoing": 0, "incoming": 0}
        said: dict[str, str | None] = {"outgoing": None, "incoming": None}
        for fade_idx in range(fade_frames):
            frame_a, why_a = _next_frame(active_iter)
            frame_b, why_b = _next_frame(next_iter)
            for side, frame, why in (("outgoing", frame_a, why_a), ("incoming", frame_b, why_b)):
                if frame is None:
                    missing[side] += 1
                    said[side] = said[side] or why

            if frame_a is None is frame_b and last_a is None is last_b:
                self._hold_last(fade_frames - fade_idx, "both sides of a fade were empty", "")
                return

            if black is None:
                ref = frame_a if frame_a is not None else frame_b
                assert ref is not None  # noqa: S101
                black, blend_buf = _match_blend_bufs(ref, blend_buf, self._semi_planar)

            frame_a, last_a = _hold_or_fallback(frame_a, last_a, black)
            frame_b, last_b = _hold_or_fallback(frame_b, last_b, black)

            alpha = (fade_idx + 1) / fade_frames
            blend_crossfade(frame_a, frame_b, alpha, out=blend_buf)
            self._write(blend_buf)
        _log_short_fade(missing, said, fade_frames)

    def _write(self, frame: np.ndarray) -> None:
        self._sink.write_frame(frame)
        self._last_written = frame
        self._frames_written += 1
        if self._progress_callback and self._frames_written % self._report_interval == 0:
            self._progress_callback(self._frames_written, self._total_frames)
        self._emit_preview(frame)

    def _hold_last(self, missing: int, why: str, clip: str) -> None:
        """Write the last frame again for each missing one, so the film keeps its length."""
        logger.warning(
            "Frame underrun%s: %s; holding the last frame for the missing %d (%.1f%% of the film)",
            f" in {clip}" if clip else "",
            why,
            missing,
            missing / max(self._total_frames, 1) * 100,
        )
        held = self._last_written
        if held is None:
            logger.error("Frame underrun before any frame was written; %d frames lost", missing)
            return
        for _ in range(missing):
            self._write(held)

    def _emit_preview(self, frame: np.ndarray) -> None:
        from immich_memories.processing.frame_preview import maybe_emit_preview

        self._last_preview_time = maybe_emit_preview(
            frame,
            self._last_preview_time,
            self._frame_preview_callback,
            self._is_hdr,
            self._height,
            self._width,
            self._semi_planar,
        )
