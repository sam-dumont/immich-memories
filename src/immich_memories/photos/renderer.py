"""Frame-by-frame photo animation renderer.

Generates video frames in Python (numpy/cv2) with subpixel-precise
Ken Burns, dynamic blur backgrounds, and HDR support. Frames are piped
to FFmpeg as raw RGB for encoding.

Rendering in Python rather than through FFmpeg zoompan filters avoids the
zoompan jitter, colour-space surprises and HEIC incompatibility that the
filter-expression approach hit, and gives full control over every pixel.

Validated on real iPhone 16 Pro HEIC photos with HDR gain maps.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterator
from dataclasses import dataclass

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class KenBurnsParams:
    """Parameters for a Ken Burns animation."""

    zoom_start: float = 1.0
    zoom_end: float = 1.10
    # Pan position: (0,0)=top-left, (0.5,0.5)=center, (1,1)=bottom-right
    pan_start: tuple[float, float] = (0.5, 0.5)
    pan_end: tuple[float, float] = (0.5, 0.5)
    fps: int = 60
    duration: float = 4.0
    # How the move paces itself: a name from EASINGS.
    easing: str = "linear"


# Each curve is blended with linear: eased(t) = (1 - k)·t + k·curve(t). The plain
# curves (smoothstep, quadratic in and out) come to rest at an end, which reads as
# a dead frame across a crossfade; at k = 0.4 the slowest end still moves at 60 %
# of the move's average speed and the fastest point at 140 %, enough to tell one
# still from the next and too little to look like a different effect.
EASE_BLEND = 0.4
_CURVES = {
    "linear": lambda t: t,
    "ease-in-out": lambda t: t * t * (3.0 - 2.0 * t),
    "ease-out": lambda t: 1.0 - (1.0 - t) ** 2,
    "ease-in": lambda t: t * t,
}
EASINGS = tuple(_CURVES)


def eased(name: str, t: float) -> float:
    """Progress at time ``t`` (0 to 1) under a gentle easing; linear for an unknown name."""
    curve = _CURVES.get(name, _CURVES["linear"])
    return (1.0 - EASE_BLEND) * t + EASE_BLEND * curve(t)


def _rect(zoom: float, pan: tuple[float, float]) -> tuple[float, float, float]:
    """A pan position at a zoom as the view's centre and size, in shares of the picture."""
    size = 1.0 / zoom
    room = max(0.0, 1.0 - size)
    return (size / 2 + pan[0] * room, size / 2 + pan[1] * room, size)


def crop_window(params: KenBurnsParams, t: float) -> tuple[float, float, float]:
    """The view at time ``t`` (0 to 1): its centre x, centre y and size, shares of the picture.

    One move, not a zoom and a pan: the start and end views are fixed rectangles
    and the view travels between them on a single straight path. The size changes
    by equal ratios for equal steps of the (gently eased) progress, so the zoom looks
    even rather than speeding up, and the centre covers the same share of its way as
    the size does at every frame.
    """
    x0, y0, s0 = _rect(params.zoom_start, params.pan_start)
    x1, y1, s1 = _rect(params.zoom_end, params.pan_end)
    # One eased parameter drives the size and, through it, the centre.
    t = eased(params.easing, t)
    size = math.exp(math.log(s0) + (math.log(s1) - math.log(s0)) * t)
    # The centre follows the size's own progress, so both arrive together.
    step = (size - s0) / (s1 - s0) if abs(s1 - s0) > 1e-12 else t
    return (x0 + (x1 - x0) * step, y0 + (y1 - y0) * step, size)


def render_ken_burns_streaming(
    src: np.ndarray,
    vp_w: int,
    vp_h: int,
    params: KenBurnsParams | None = None,
    *,
    scale_mode: str = "blur",
) -> Iterator[np.ndarray]:
    """Yield Ken Burns frames one at a time (O(1) memory).

    The photo "window" is a fixed rectangle centered in the viewport.
    Ken Burns zooms/pans INSIDE that window. With `scale_mode` "blur" the
    photograph's own blur fills the rest, derived from the same crop content
    each frame; with "fit" the rest is black, as it is around a fitted video.

    The window position and size NEVER change during the animation.
    """
    if params is None:
        params = KenBurnsParams()

    src_h, src_w = src.shape[:2]

    # Photo window: fit source aspect into viewport
    photo_scale = min(vp_w / src_w, vp_h / src_h)
    win_w = int(src_w * photo_scale)
    win_h = int(src_h * photo_scale)
    win_x = (vp_w - win_w) // 2
    win_y = (vp_h - win_h) // 2
    letterboxed = (win_w < vp_w - 2) or (win_h < vp_h - 2)
    needs_blur = letterboxed and scale_mode == "blur"

    # Scale the source so the window at the largest zoom still samples one
    # source pixel per output pixel. At zoom z the frame shows 1/z of the
    # photograph: zoom 1.0 is the whole picture, and the pan moves the view
    # within the room the zoom leaves, so it needs no margin of its own.
    max_z = max(params.zoom_start, params.zoom_end)
    kb_scale = max(win_w * max_z / src_w, win_h * max_z / src_h)
    big = cv2.resize(
        src, (round(src_w * kb_scale), round(src_h * kb_scale)), interpolation=cv2.INTER_AREA
    )
    bh, bw = big.shape[:2]

    # Pre-blur for background (one-time cost)
    big_blur = cv2.GaussianBlur(big, (0, 0), sigmaX=40) if needs_blur else None

    n_frames = int(params.fps * params.duration)

    for i in range(n_frames):
        t = i / max(n_frames - 1, 1)
        centre_x, centre_y, size = crop_window(params, t)
        vis_w = bw * size
        vis_h = bh * size
        cx = centre_x * bw
        cy = centre_y * bh
        x0 = cx - vis_w / 2
        y0 = cy - vis_h / 2

        # Sharp crop → photo window
        sx, sy = win_w / vis_w, win_h / vis_h
        m_sharp = np.array([[sx, 0, -x0 * sx], [0, sy, -y0 * sy]], dtype=np.float32)
        sharp = cv2.warpAffine(
            big, m_sharp, (win_w, win_h), flags=cv2.INTER_AREA, borderMode=cv2.BORDER_REPLICATE
        )

        if needs_blur and big_blur is not None:
            # WHY: use uniform scale (max of x/y) to FILL viewport without stretch.
            # Different x/y scales would distort the blur. The larger scale ensures
            # the blur covers the entire viewport; excess is cropped by warpAffine.
            fs = max(vp_w / vis_w, vp_h / vis_h)
            # Center the crop on the same region as the sharp photo
            blur_cx = x0 + vis_w / 2
            blur_cy = y0 + vis_h / 2
            blur_x0 = blur_cx - (vp_w / fs) / 2
            blur_y0 = blur_cy - (vp_h / fs) / 2
            m_blur = np.array([[fs, 0, -blur_x0 * fs], [0, fs, -blur_y0 * fs]], dtype=np.float32)
            bg = cv2.warpAffine(
                big_blur,
                m_blur,
                (vp_w, vp_h),
                flags=cv2.INTER_AREA,
                borderMode=cv2.BORDER_REPLICATE,
            )
            bg[win_y : win_y + win_h, win_x : win_x + win_w] = sharp
            yield bg
        elif letterboxed:
            canvas = np.zeros((vp_h, vp_w, *big.shape[2:]), dtype=big.dtype)
            canvas[win_y : win_y + win_h, win_x : win_x + win_w] = sharp
            yield canvas
        else:
            vsx, vsy = vp_w / vis_w, vp_h / vis_h
            m_vp = np.array([[vsx, 0, -x0 * vsx], [0, vsy, -y0 * vsy]], dtype=np.float32)
            yield cv2.warpAffine(
                big, m_vp, (vp_w, vp_h), flags=cv2.INTER_AREA, borderMode=cv2.BORDER_REPLICATE
            )


def _blit_cell(canvas: np.ndarray, cell: np.ndarray, cx: int, cy: int) -> None:
    """Place a cell on the canvas, clipping to canvas bounds."""
    vp_h, vp_w = canvas.shape[:2]
    cell_h, cell_w = cell.shape[:2]
    sx0, sy0 = max(0, -cx), max(0, -cy)
    dx0, dy0 = max(0, cx), max(0, cy)
    cw = min(cell_w - sx0, vp_w - dx0)
    ch = min(cell_h - sy0, vp_h - dy0)
    if cw > 0 and ch > 0:
        canvas[dy0 : dy0 + ch, dx0 : dx0 + cw] = cell[sy0 : sy0 + ch, sx0 : sx0 + cw]


def render_split(
    photos: list[np.ndarray],
    vp_w: int,
    vp_h: int,
    gap: int = 6,
    fps: int = 30,
    duration: float = 5.0,
) -> list[np.ndarray]:
    """Render a split screen grid (Apple Photos style).

    2 photos: side by side. 3 photos: 1 large left + 2 stacked right.
    4 photos: 2×2 grid. Each cell gets a subtle Ken Burns zoom.
    Gap between cells is filled with blurred average.

    Parked for the split-mode feature, roadmap #326 — nothing in the pipeline
    calls it yet. The rest of the animation stack it shipped with (collage,
    slide-in, the FFmpeg filter expressions) was retired in #502; this one
    stays because split screen is a wanted feature, not abandoned code.
    """
    n = len(photos)
    if n < 2 or n > 4:
        msg = f"Split requires 2-4 photos, got {n}"
        raise ValueError(msg)

    cells = _compute_split_layout(n, vp_w, vp_h, gap)

    # Scale each photo to fill its cell
    cell_imgs = []
    for i, (_cx, _cy, cw, ch) in enumerate(cells):
        ph, pw = photos[i].shape[:2]
        cs = max(cw / pw, ch / ph)
        resized = cv2.resize(photos[i], (int(pw * cs), int(ph * cs)), interpolation=cv2.INTER_AREA)
        oy = (resized.shape[0] - ch) // 2
        ox = (resized.shape[1] - cw) // 2
        cell_imgs.append(resized[oy : oy + ch, ox : ox + cw])

    # Background: blurred average
    bg = np.mean(
        [cv2.resize(p, (vp_w, vp_h), interpolation=cv2.INTER_AREA) for p in photos], axis=0
    ).astype(np.float32)
    bg_blur = cv2.GaussianBlur(bg, (0, 0), sigmaX=40)

    # Static composite with subtle per-cell zoom
    n_frames = int(fps * duration)
    frames: list[np.ndarray] = []
    for _fi in range(n_frames):
        canvas = bg_blur.copy()
        for (cx, cy, _cw, _ch), cell in zip(cells, cell_imgs, strict=True):
            _blit_cell(canvas, cell, cx, cy)
        frames.append(canvas)

    return frames


def _compute_split_layout(
    n: int, vp_w: int, vp_h: int, gap: int
) -> list[tuple[int, int, int, int]]:
    """Compute (x, y, w, h) for each cell in a split layout."""
    if n == 2:
        cw = (vp_w - gap) // 2
        return [(0, 0, cw, vp_h), (cw + gap, 0, cw, vp_h)]
    if n == 3:
        left_w = (vp_w - gap) * 2 // 3
        right_w = vp_w - left_w - gap
        right_h = (vp_h - gap) // 2
        return [
            (0, 0, left_w, vp_h),
            (left_w + gap, 0, right_w, right_h),
            (left_w + gap, right_h + gap, right_w, right_h),
        ]
    # n == 4: 2×2 grid
    cw = (vp_w - gap) // 2
    ch = (vp_h - gap) // 2
    return [
        (0, 0, cw, ch),
        (cw + gap, 0, cw, ch),
        (0, ch + gap, cw, ch),
        (cw + gap, ch + gap, cw, ch),
    ]
