"""Animated satellite map fly-over — van Wijk smooth zoom (d3.interpolateZoom)."""

from __future__ import annotations

import contextlib
import logging
import math
import subprocess
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from itertools import starmap
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from immich_memories.processing.encoding_plan import EncodingPlan
from immich_memories.processing.hardware_encode import apply_hardware_encode
from immich_memories.processing.map_move_timing import MapMoveTiming
from immich_memories.processing.memory_budget import available_cpus, memory_budget
from immich_memories.titles.ffmpeg_pipe import StderrDrain

from .colors import ceil_rgb_for_hdr
from .encoding import standalone_title_encoding_plan, title_color_filter, title_encoder_args
from .map_renderer import (
    _draw_gradient_band,
    _fit_pin_label_font,
    _fit_title_lines,
    _overlay_composite,
)
from .map_tiles import CachedStaticMap, tile_cache

logger = logging.getLogger(__name__)

_CITY_ZOOM = 14  # Reference framing at 1080p; more pixels need a higher tile zoom.
_MAX_TILE_ZOOM = 19
_MIN_ZOOM_FLOOR = 3  # Never zoom out past this
_RHO = math.sqrt(2)  # Zoom/pan trade-off (d3 default)
_SAT_URL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
)

_ViewInterp = Callable[[float], tuple[float, float, float]]
# A card's name sits in the lower third in either orientation, clear of the pin in the middle.
_CARD_LABEL_Y = 0.72
_TITLE_FADE_SECONDS = 0.5
_PIN_LABEL_SHARE = 0.034


@dataclass
class _PinData:
    """Pin with optional label."""

    lat: float
    lon: float
    name: str | None = None


@dataclass
class _FlyConfig:
    """Animation state: interpolators, pins, overlay, dimensions."""

    interps: list[_ViewInterp] = field(default_factory=list)
    pins: list[_PinData] = field(default_factory=list)
    title_overlay: Image.Image | None = None
    width: int = 1920
    height: int = 1080
    dest_zoom: float = 9.0  # zoom level at destination (pins reference size)
    # Graphics drawn straight onto the tiles, so they need the HDR ceiling (#506)
    hdr: bool = False


# -- Web Mercator (zoom-0 pixel space, 256 px = world) ---------------------


def _to_world(lat: float, lon: float) -> tuple[float, float]:
    """(lat, lon) → zoom-0 pixel coords."""
    x = (lon + 180.0) / 360.0 * 256.0
    lat_r = math.radians(max(-85.0, min(85.0, lat)))
    y = (1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * 256.0
    return x, y


def _to_latlon(wx: float, wy: float) -> tuple[float, float]:
    """Zoom-0 pixel coords → (lat, lon)."""
    lon = wx / 256.0 * 360.0 - 180.0
    n = math.pi - 2.0 * math.pi * wy / 256.0
    return math.degrees(math.atan(math.sinh(n))), lon


def _geo_to_screen(
    pin_lat: float,
    pin_lon: float,
    cam_lat: float,
    cam_lon: float,
    zoom: float,
    w: int,
    h: int,
) -> tuple[int, int]:
    """(lat, lon) → screen pixel given camera state."""
    pw, py_w = _to_world(pin_lat, pin_lon)
    cw, cy_w = _to_world(cam_lat, cam_lon)
    scale = 2.0**zoom
    return int(w / 2 + (pw - cw) * scale), int(h / 2 + (py_w - cy_w) * scale)


def _van_wijk(
    p0: tuple[float, float, float],
    p1: tuple[float, float, float],
    rho: float = _RHO,
) -> _ViewInterp:
    """Optimal zoom+pan: (cx,cy,w) views → f(t) interpolator."""
    ux0, uy0, w0 = p0
    ux1, uy1, w1 = p1
    dx, dy = ux1 - ux0, uy1 - uy0
    d2 = dx * dx + dy * dy
    rho2, rho4 = rho * rho, rho**4

    if d2 < 1e-12:
        s_tot = math.log(w1 / w0) / rho if w0 > 0 and w1 > 0 else 0.0

        def _pure_zoom(t: float) -> tuple[float, float, float]:
            return ux0 + t * dx, uy0 + t * dy, w0 * math.exp(rho * t * s_tot)

        return _pure_zoom

    d1 = math.sqrt(d2)
    b0 = (w1 * w1 - w0 * w0 + rho4 * d2) / (2.0 * w0 * rho2 * d1)
    b1 = (w1 * w1 - w0 * w0 - rho4 * d2) / (2.0 * w1 * rho2 * d1)
    r0 = math.log(math.sqrt(b0 * b0 + 1.0) - b0)
    r1 = math.log(math.sqrt(b1 * b1 + 1.0) - b1)
    s_tot = (r1 - r0) / rho
    coshr0 = math.cosh(r0)
    sinhr0 = math.sinh(r0)

    def _zoom_pan(t: float) -> tuple[float, float, float]:
        s = t * s_tot
        u = w0 / (rho2 * d1) * (coshr0 * math.tanh(rho * s + r0) - sinhr0)
        return ux0 + u * dx, uy0 + u * dy, w0 * coshr0 / math.cosh(rho * s + r0)

    return _zoom_pan


def _linear_pan(p0: tuple[float, float, float], p1: tuple[float, float, float]) -> _ViewInterp:
    """Straight pan at fixed zoom for short distances."""
    ux0, uy0, w0 = p0
    ux1, uy1, _ = p1
    w_use = max(w0, p1[2])  # wider viewport so both points stay visible

    # No easing here: every caller hands in progress the map-move schedule already eased.
    def _pan(t: float) -> tuple[float, float, float]:
        return ux0 + t * (ux1 - ux0), uy0 + t * (uy1 - uy0), w_use

    return _pan


def _pick_interpolator(
    p0: tuple[float, float, float],
    p1: tuple[float, float, float],
) -> _ViewInterp:
    """Pull back for a route that does not fit the close endpoint view; otherwise pan."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    d = math.sqrt(dx * dx + dy * dy)
    if d * 1.5 <= min(p0[2], p1[2]):
        logger.info("Short hop — linear pan within the city view")
        return _linear_pan(p0, p1)
    return _van_wijk(p0, p1)


# ---------------------------------------------------------------------------
# Per-frame rendering
# ---------------------------------------------------------------------------


def _render_satellite(lat: float, lon: float, zoom: float, w: int, h: int) -> Image.Image:
    """Satellite tiles at fractional zoom via oversample + resize."""
    z_int = max(1, min(19, math.ceil(zoom)))
    frac = z_int - zoom
    oversample = 2.0**frac

    rw = int(math.ceil(w * oversample))
    rh = int(math.ceil(h * oversample))

    sm = CachedStaticMap(rw, rh, url_template=_SAT_URL)

    try:
        img = sm.render(zoom=z_int, center=[lon, lat])
    except Exception as e:  # noqa: BLE001
        # WHY so broad: the tiles come through a third-party HTTP client and a
        # decoder, and an offline box has produced OSError, RuntimeError and a
        # ValueError out of a truncated body. One grey frame beats a dead render.
        # No coordinates in the line: warnings travel into run reports and issues.
        logger.warning("Tile fetch failed at zoom %d: %s", z_int, e)
        img = Image.new("RGB", (rw, rh), (40, 50, 60))

    if img.size != (w, h):
        img = _resize_satellite_frame(img, w, h)
    return img


def _resize_satellite_frame(image: Image.Image, width: int, height: int) -> Image.Image:
    budget = memory_budget()
    cpus = available_cpus()
    # Fractional source boxes can change Lanczos weights. Equal power-of-two
    # strips keep each source boundary exactly representable.
    workers = 4 if cpus >= 4 and height % 4 == 0 else 2
    # Parallel strips keep an extra output frame and concurrent intermediates.
    if (
        cpus < 2
        or height % 2
        or width * height < 1920 * 1080
        or budget is None
        or budget.size < 4 * 2**30
    ):
        return image.resize((width, height), Image.Resampling.LANCZOS)

    def resize_strip(index: int) -> tuple[int, Image.Image]:
        top = index * height // workers
        bottom = (index + 1) * height // workers
        # Keep global source coordinates so each strip has the same filter
        # support and sampling positions as the full-frame Lanczos operation.
        box = (0, top * image.height / height, image.width, bottom * image.height / height)
        return top, image.resize((width, bottom - top), Image.Resampling.LANCZOS, box=box)

    result = Image.new("RGB", (width, height))
    with ThreadPoolExecutor(workers) as pool:
        for top, strip in pool.map(resize_strip, range(workers)):
            result.paste(strip, (0, top))
    return result


def _draw_pins(
    frame: Image.Image,
    cam_lat: float,
    cam_lon: float,
    zoom: float,
    cfg: _FlyConfig,
) -> Image.Image:
    """Draw destination pins + city labels, fading in near destination zoom."""
    pins, dest_zoom, w, h = cfg.pins, cfg.dest_zoom, cfg.width, cfg.height
    if not pins:
        return frame
    pin_alpha = max(0.0, min(1.0, (zoom - dest_zoom + 2.5) / 2.5))
    if pin_alpha < 0.05:
        return frame

    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    base_r = max(6, int(min(w, h) * 0.012))
    # 3.4 % of the short side: 37 px on a 1080p frame, 73 px at 4K, the same in portrait.
    base_font_size = max(12, int(min(w, h) * _PIN_LABEL_SHARE))
    # Labels never wrap next to a pin, so a long name only has shrink + clamp (#1954).
    label_margin = int(w * 0.02)
    label_max_width = w - 2 * label_margin
    stroke = max(1, int(min(w, h) * 0.003))
    a_w, a_f = int(200 * pin_alpha), int(230 * pin_alpha)
    a_l, a_s = int(220 * pin_alpha), int(200 * pin_alpha)
    white = ceil_rgb_for_hdr((255, 255, 255)) if cfg.hdr else (255, 255, 255)

    for pin in pins:
        sx, sy = _geo_to_screen(pin.lat, pin.lon, cam_lat, cam_lon, zoom, w, h)
        margin = base_r * 3
        if sx < -margin or sx > w + margin or sy < -margin or sy > h + margin:
            continue
        r_out = base_r + 3
        draw.ellipse((sx - r_out, sy - r_out, sx + r_out, sy + r_out), fill=(*white, a_w))
        draw.ellipse((sx - base_r, sy - base_r, sx + base_r, sy + base_r), fill=(232, 93, 74, a_f))

        if pin.name:
            font, label_w = _fit_pin_label_font(pin.name, draw, base_font_size, label_max_width)
            lx = sx - label_w // 2
            lx = max(label_margin, min(w - label_margin - label_w, lx))
            ly = sy - r_out - getattr(font, "size", 14) - 6
            # A dark outline keeps the name readable over snow, sea or city alike.
            draw.text(
                (lx, ly),
                pin.name,
                fill=(*white, a_l),
                font=font,
                stroke_width=stroke,
                stroke_fill=(0, 0, 0, a_s),
            )

    return Image.alpha_composite(frame.convert("RGBA"), overlay).convert("RGB")


def _render_frame(
    lat: float,
    lon: float,
    zoom: float,
    cfg: _FlyConfig,
) -> Image.Image:
    """Render satellite + pins + title for one animation frame."""
    frame = _render_satellite(lat, lon, zoom, cfg.width, cfg.height)
    return _draw_pins(frame, lat, lon, zoom, cfg)


def _city_view_width(width: int, height: int) -> float:
    # Keep the short side's geographic span, including when the film is portrait.
    return 1080.0 / 2**_CITY_ZOOM * width / min(width, height)


def _destination_overview(
    destinations: list[tuple[float, float]],
    width: int,
    height: int,
    free: tuple[float, float] = (0.0, 1.0),
) -> tuple[float, float, float]:
    """Compute the (wx, wy, w) view that shows every destination inside `free`.

    `free` is the band of the frame's height, as shares from the top, where the stops may sit:
    the part the trip title leaves open. The view is widened until the stops fit that band and
    shifted so they sit in its middle.
    """
    worlds = list(starmap(_to_world, destinations))
    wxs, wys = [v[0] for v in worlds], [v[1] for v in worlds]
    cx = (max(wxs) + min(wxs)) / 2
    cy = (max(wys) + min(wys)) / 2
    span_x = (max(wxs) - min(wxs)) if len(wxs) > 1 else 0.0
    span_y = (max(wys) - min(wys)) if len(wys) > 1 else 0.0
    top, bottom = free
    # 1.5x padding around pins (not 2x — keeps destinations more visible)
    w_overview = max(span_x * 1.5, span_y * (width / height) * 1.5 / (bottom - top))
    # Clamp: min zoom _CITY_ZOOM (close), max zoom _MIN_ZOOM_FLOOR (world)
    w_overview = max(
        _city_view_width(width, height), min(width / (2.0**_MIN_ZOOM_FLOOR), w_overview)
    )
    # Screen y grows with world y, so moving the camera south lifts the stops up the frame.
    visible_h = w_overview * height / width
    return cx, cy + (0.5 - (top + bottom) / 2) * visible_h, w_overview


def _free_band(title_overlay: Image.Image | None, height: int) -> tuple[float, float]:
    """The share of the frame's height the stops may use: above the title's band, with room
    over each pin for its name. Without a title, the whole frame."""
    if title_overlay is None:
        return 0.0, 1.0
    alpha_rows = title_overlay.getchannel("A").getbbox()
    if alpha_rows is None:
        return 0.0, 1.0
    band_top = alpha_rows[1] / height
    label_room = 0.12
    return label_room, max(label_room + 0.1, band_top - 0.04)


def create_map_fly_video(
    departure: tuple[float, float],
    destinations: list[tuple[float, float]],
    title_text: str,
    output_path: Path,
    width: int = 1920,
    height: int = 1080,
    duration: float = 7.0,
    fps: float = 30.0,
    timing: MapMoveTiming | None = None,
    encoding_plan: EncodingPlan | None = None,
    destination_names: list[str] | None = None,
    animated_background: bool = True,
) -> Path:
    """Fly from home to the first trip stop, then hold close on it with the trip title.

    Van Wijk smooth zoom for a long flight, a pan for a short one, eased by the
    map-move schedule so the last `timing.hold_seconds` sit still on the first
    stop with the trip title up. Later stops arrive with their own location cards.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    timing = timing or MapMoveTiming()
    logger.info("Map fly: %d stops (%.1fs, %dx%d)", len(destinations), duration, width, height)

    # Only named stops get a pin: an unlabelled dot tells the viewer nothing.
    names = destination_names or []
    pins = [
        _PinData(lat=lat, lon=lon, name=names[i])
        for i, (lat, lon) in enumerate(destinations[:1])
        if i < len(names) and names[i]
    ]

    hdr = bool(encoding_plan and encoding_plan.hdr)
    title_overlay = _render_title_overlay(title_text, width, height, hdr)
    dep_wx, dep_wy = _to_world(*departure)
    w_city = _city_view_width(width, height)
    # Leave the first stop and its name clear of the title during the landing hold.
    dest_cx, dest_cy, w_overview = _destination_overview(
        destinations[:1], width, height, _free_band(title_overlay, height)
    )
    interp = _pick_interpolator((dep_wx, dep_wy, w_city), (dest_cx, dest_cy, w_overview))

    dz = math.log2(width / w_overview) if w_overview > 0 else float(_CITY_ZOOM)
    cfg = _FlyConfig(
        interps=[interp],
        pins=pins,
        title_overlay=title_overlay,
        width=width,
        height=height,
        dest_zoom=dz,
        hdr=hdr,
    )
    progress = timing.schedule(duration, fps)
    title_in = max(1, round(_TITLE_FADE_SECONDS * fps))
    # The title rises with the take-off and stays: the hold is where it is read.
    alphas = [min(1.0, i / title_in) for i in range(len(progress))]

    tile_cache.clear()
    rendered = _create_map_video(
        cfg, output_path, progress, alphas, fps, encoding_plan, animated_background
    )
    logger.info("Map fly done: %d frames (%d rendered)", len(progress), rendered)
    return output_path


def create_map_move_video(
    came_from: tuple[float, float],
    destination: tuple[float, float],
    label: str,
    output_path: Path,
    duration: float,
    width: int = 1920,
    height: int = 1080,
    fps: float = 30.0,
    timing: MapMoveTiming | None = None,
    encoding_plan: EncodingPlan | None = None,
    animated_background: bool = True,
) -> Path:
    """A location card: fly from the last place to this one, then hold on it with its name.

    Both endpoints show the town close up, with the same geographic framing at
    every resolution. Longer routes pull back and descend again; a hop already
    inside the city view pans. The name fades in as the camera lands.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    timing = timing or MapMoveTiming()
    w_card = _city_view_width(width, height)
    start = (*_to_world(*came_from), w_card)
    end = (*_to_world(*destination), w_card)
    hdr = bool(encoding_plan and encoding_plan.hdr)
    cfg = _FlyConfig(
        interps=[_pick_interpolator(start, end)],
        pins=[_PinData(lat=destination[0], lon=destination[1])],
        title_overlay=_render_title_overlay(label, width, height, hdr, anchor=_CARD_LABEL_Y),
        width=width,
        height=height,
        dest_zoom=math.log2(width / w_card),
        hdr=hdr,
    )
    progress = timing.schedule(duration, fps)
    tile_cache.clear()
    rendered = _create_map_video(
        cfg,
        output_path,
        progress,
        timing.label_alphas(duration, fps),
        fps,
        encoding_plan,
        animated_background,
    )
    logger.info(
        "Map move card: %d frames (%d rendered), %.1fs",
        len(progress),
        rendered,
        duration,
    )
    return output_path


def _view_at(
    t: float,
    interps: list[_ViewInterp],
    n: int,
    w: int,
) -> tuple[float, float, float]:
    """Get (lat, lon, zoom) at animation time t ∈ [0, 1]."""
    seg_t = t * n
    idx = min(int(seg_t), n - 1)
    local = max(0.0, min(1.0, seg_t - idx))

    wx, wy, vw = interps[idx](local)
    lat, lon = _to_latlon(wx, wy)
    zoom = math.log2(w / vw) if vw > 0 else float(_CITY_ZOOM)
    return lat, lon, max(float(_MIN_ZOOM_FLOOR), min(float(_MAX_TILE_ZOOM), zoom))


def _frame_at(progress: float, cfg: _FlyConfig) -> tuple[Image.Image, float]:
    """The rendered map and its zoom at a point of the flight (0 = start, 1 = landed)."""
    lat, lon, z = _view_at(progress, cfg.interps, len(cfg.interps), cfg.width)
    return _render_frame(lat, lon, z, cfg), z


def _pipe_frames(
    cfg: _FlyConfig,
    output_path: Path,
    progress: list[float],
    overlay_alphas: list[float],
    fps: float,
    encoding_plan: EncodingPlan | None,
) -> int:
    """Render each frame's map, lay the overlay on it, and pipe raw RGB to FFmpeg.

    A frame at the same point of the flight as the one before is the same map, so
    the still hold costs one render however long it is. Returns the maps rendered.
    """
    plan = encoding_plan or standalone_title_encoding_plan()
    total = len(progress)
    duration = total / fps
    w, h = cfg.width, cfg.height

    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "rawvideo",
        "-vcodec",
        "rawvideo",
        "-s",
        f"{w}x{h}",
        "-pix_fmt",
        "rgb24",
        "-r",
        str(fps),
        "-i",
        "-",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=48000:cl=stereo",
        "-vf",
        title_color_filter(plan),
        *title_encoder_args(plan),
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-t",
        str(duration),
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    cmd = apply_hardware_encode(cmd, pixel_format=plan.pixel_format)

    proc = subprocess.Popen(  # noqa: S603
        cmd,
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stdin is not None  # noqa: S101
    stderr_drain = StderrDrain(proc).start()

    last: tuple[float, Image.Image, float] | None = None
    rendered = 0
    with contextlib.suppress(BrokenPipeError):
        for i, (t, alpha) in enumerate(zip(progress, overlay_alphas, strict=True)):
            if last is None or last[0] != t:
                frame, z = _frame_at(t, cfg)
                last = (t, frame, z)
                rendered += 1
            _, frame, z = last
            if cfg.title_overlay is not None and alpha > 0.01:
                frame = _overlay_composite(frame, cfg.title_overlay, alpha)
            proc.stdin.write(np.array(frame).tobytes())
            if i % 30 == 0:
                logger.info("Map fly %d/%d (z=%.1f, %d tiles)", i, total, z, len(tile_cache))

    proc.stdin.close()
    proc.wait()
    stderr_tail = stderr_drain.stop()
    if proc.returncode != 0:
        raise RuntimeError(f"Map fly FFmpeg failed: {stderr_tail[-500:]}")
    return rendered


def _render_title_overlay(
    text: str, w: int, h: int, hdr: bool = False, anchor: float | None = None
) -> Image.Image | None:
    """Pre-render title text as an RGBA overlay — big, centered.

    `anchor` is the text block's vertical centre as a share of the height; by default
    the lower quarter in landscape and the middle in portrait.
    """
    if not text:
        return None

    is_portrait = h > w
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    fs = int(w * 0.12) if is_portrait else int(h * 0.09)
    # 6 % margin either side: a long compound name shrinks to stay inside it
    # instead of overflowing the frame edge (#1954).
    safe_width = int(w * 0.88)
    lines, font = _fit_title_lines(text, draw, base_size=fs, bold=True, max_width=safe_width)

    white = ceil_rgb_for_hdr((255, 255, 255)) if hdr else (255, 255, 255)
    line_h = int(getattr(font, "size", fs) * 1.2)
    total_h = line_h * len(lines)
    if anchor is None:
        anchor = 0.5 if is_portrait else 0.75
    block_y = int(h * anchor) - total_h // 2
    band_pad = int(getattr(font, "size", fs) * 0.8)
    _draw_gradient_band(draw, block_y - band_pad, total_h + 2 * band_pad, w, h)
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        x = (w - tw) // 2
        y = block_y + i * line_h
        draw.text((x + 2, y + 2), line, fill=(0, 0, 0, 130), font=font)
        draw.text((x, y), line, fill=(*white, 240), font=font)

    return img


def _map_plate(progress: float, cfg: _FlyConfig, show_title: bool) -> Image.Image:
    lat, lon, zoom = _view_at(progress, cfg.interps, len(cfg.interps), cfg.width)
    scale = min(1.0, 360 / min(cfg.width, cfg.height))
    w, h = round(cfg.width * scale), round(cfg.height * scale)
    # A smaller raster needs a lower pixel zoom to keep the same geographic viewport.
    frame = _render_satellite(lat, lon, zoom + math.log2(w / cfg.width), w, h)
    frame = frame.resize((cfg.width, cfg.height), Image.Resampling.BILINEAR)
    # The route overview still needs its destination marker, even at its wider zoom.
    frame = _draw_pins(frame, lat, lon, zoom, replace(cfg, dest_zoom=zoom))
    if show_title and cfg.title_overlay is not None:
        frame = _overlay_composite(frame, cfg.title_overlay, 1.0)
    return frame


def _plate_frames(
    plates: list[Image.Image], total: int, fps: float, arrival: float, fade: float
) -> Iterator[bytes]:
    # Static spans reuse the same bytes; only the two brief fades create transient frames.
    raw = [plate.tobytes() for plate in plates]
    for i in range(total):
        t = i / fps
        if t < arrival / 3:
            yield raw[0]
        elif t < arrival / 3 + fade:
            yield Image.blend(plates[0], plates[1], (t - arrival / 3) / fade).tobytes()
        elif t < arrival - fade:
            yield raw[1]
        elif t < arrival:
            yield Image.blend(plates[1], plates[2], (t - arrival + fade) / fade).tobytes()
        else:
            yield raw[2]


def _pipe_map_plates(
    cfg: _FlyConfig,
    output_path: Path,
    progress: list[float],
    overlay_alphas: list[float],
    fps: float,
    encoding_plan: EncodingPlan | None,
) -> int:
    from immich_memories.processing.ffmpeg_runner import write_frames_to_ffmpeg

    started = time.perf_counter()
    plan = encoding_plan or standalone_title_encoding_plan()
    total = len(progress)
    duration = total / fps
    moving = next((i for i, t in enumerate(progress) if t == 1.0), total - 1)
    arrival = max(1 / fps, moving / fps)
    fade = min(0.5, arrival / 4)
    plates = [
        _map_plate(t, cfg, i == 2 or overlay_alphas[min(1, total - 1)] > 0)
        for i, t in enumerate((0.0, 0.5, 1.0))
    ]
    synthesized = time.perf_counter()
    cmd = [
        "ffmpeg", "-y", "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", f"{cfg.width}x{cfg.height}", "-pix_fmt", "rgb24", "-r", str(fps), "-i", "-",
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
        "-vf", title_color_filter(plan), *title_encoder_args(plan),
        "-c:a", "aac", "-b:a", "128k", "-t", str(duration),
        "-movflags", "+faststart", str(output_path),
    ]  # fmt: skip
    cmd = apply_hardware_encode(cmd, pixel_format=plan.pixel_format)
    code, tail = write_frames_to_ffmpeg(
        cmd,
        _plate_frames(plates, total, fps, arrival, fade),
        wait_timeout=60,
        total_timeout=max(60, duration * 30),
    )
    if code:
        raise RuntimeError(f"Map plates FFmpeg failed: {tail[-2000:]}")
    logger.info(
        "Map plates: synthesis %.2fs; stream blends/encode %.2fs; 3 views, %d frames, %dx%d",
        synthesized - started,
        time.perf_counter() - synthesized,
        total,
        cfg.width,
        cfg.height,
    )
    return 3


def _create_map_video(
    cfg: _FlyConfig,
    output_path: Path,
    progress: list[float],
    overlay_alphas: list[float],
    fps: float,
    encoding_plan: EncodingPlan | None,
    animated_background: bool,
) -> int:
    render = _pipe_frames if animated_background else _pipe_map_plates
    try:
        return render(cfg, output_path, progress, overlay_alphas, fps, encoding_plan)
    finally:
        logger.info("Map tiles: releasing %d cached downloads", len(tile_cache))
        tile_cache.clear()
