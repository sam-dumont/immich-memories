"""Animated satellite map fly-over — van Wijk smooth zoom (d3.interpolateZoom)."""

from __future__ import annotations

import contextlib
import logging
import math
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import starmap
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from staticmap import CircleMarker, StaticMap

from immich_memories.processing.encoding_plan import EncodingPlan
from immich_memories.processing.hardware_encode import apply_hardware_encode
from immich_memories.processing.map_move_timing import MapMoveTiming
from immich_memories.titles.ffmpeg_pipe import StderrDrain

from .colors import ceil_rgb_for_hdr
from .encoding import standalone_title_encoding_plan, title_color_filter, title_encoder_args
from .map_renderer import _draw_gradient_band, _overlay_composite, _wrap_text

logger = logging.getLogger(__name__)

_CITY_ZOOM = 14  # Start/end zoom (city-level, ~30 m/px)
_MIN_ZOOM_FLOOR = 3  # Never zoom out past this
_RHO = math.sqrt(2)  # Zoom/pan trade-off (d3 default)
_SAT_URL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
)

_ViewInterp = Callable[[float], tuple[float, float, float]]
_PAN_THRESHOLD_ZOOM = 10  # If mid-transit zoom > this, pan instead of zoom
# A location card flies at region scale (about 150 km across at 1920 px): a 30 km hop
# keeps both towns in frame, and the landing shows the place among its neighbours.
_CARD_ZOOM = 11
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


_tile_cache: dict[str, bytes] = {}


class _CachedStaticMap(StaticMap):
    """StaticMap with shared cross-instance tile cache."""

    def get(self, url: str, **kwargs):
        """Return cached tile bytes or fetch + cache."""
        if url in _tile_cache:
            return 200, _tile_cache[url]
        status, content = super().get(url, **kwargs)
        if status == 200:
            _tile_cache[url] = content
        return status, content


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
    width: int,
) -> _ViewInterp:
    """Van Wijk zoom for long distances, linear pan for short hops."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    d = math.sqrt(dx * dx + dy * dy)
    mid_w = max(p0[2], p1[2], d * 1.5)
    mid_zoom = math.log2(width / mid_w) if mid_w > 0 else _CITY_ZOOM
    if mid_zoom >= _PAN_THRESHOLD_ZOOM:
        logger.info("Short hop — linear pan (mid-zoom %.1f)", mid_zoom)
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

    sm = _CachedStaticMap(rw, rh, url_template=_SAT_URL)
    sm.add_marker(CircleMarker((lon, lat), "#00000000", 1))  # required by staticmap

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
        img = img.resize((w, h), Image.Resampling.LANCZOS)
    return img


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

    from .map_renderer import _get_font

    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    base_r = max(6, int(min(w, h) * 0.012))
    # 3.4 % of the short side: 37 px on a 1080p frame, 73 px at 4K, the same in portrait.
    font = _get_font(max(12, int(min(w, h) * _PIN_LABEL_SHARE)), bold=True)
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
            bbox = draw.textbbox((0, 0), pin.name, font=font)
            lx = sx - (bbox[2] - bbox[0]) // 2
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


def _destination_overview(
    destinations: list[tuple[float, float]],
    width: int,
    height: int,
) -> tuple[float, float, float]:
    """Compute (wx, wy, w) that shows all destinations with 2x padding."""
    worlds = list(starmap(_to_world, destinations))
    wxs, wys = [v[0] for v in worlds], [v[1] for v in worlds]
    cx, cy = sum(wxs) / len(wxs), sum(wys) / len(wys)
    span_x = (max(wxs) - min(wxs)) if len(wxs) > 1 else 0.0
    span_y = (max(wys) - min(wys)) if len(wys) > 1 else 0.0
    # 1.5x padding around pins (not 2x — keeps destinations more visible)
    w_overview = max(span_x * 1.5, span_y * (width / height) * 1.5)
    # Clamp: min zoom _CITY_ZOOM (close), max zoom _MIN_ZOOM_FLOOR (world)
    w_overview = max(width / (2.0**_CITY_ZOOM), min(width / (2.0**_MIN_ZOOM_FLOOR), w_overview))
    return cx, cy, w_overview


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
) -> Path:
    """Google Earth-style fly-over from home to the trip, then a still hold on its stops.

    Van Wijk smooth zoom for a long flight, a pan for a short one, eased by the
    map-move schedule so the last `timing.hold_seconds` sit still on the named
    stops with the trip title up.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    timing = timing or MapMoveTiming()
    logger.info("Map fly: %d stops (%.1fs, %dx%d)", len(destinations), duration, width, height)

    # Only named stops get a pin: an unlabelled dot tells the viewer nothing.
    names = destination_names or []
    pins = [
        _PinData(lat=lat, lon=lon, name=names[i])
        for i, (lat, lon) in enumerate(destinations)
        if i < len(names) and names[i]
    ]

    dep_wx, dep_wy = _to_world(*departure)
    w_city = width / (2.0**_CITY_ZOOM)
    dest_cx, dest_cy, w_overview = _destination_overview(destinations, width, height)
    interp = _pick_interpolator((dep_wx, dep_wy, w_city), (dest_cx, dest_cy, w_overview), width)

    dz = math.log2(width / w_overview) if w_overview > 0 else float(_CITY_ZOOM)
    hdr = bool(encoding_plan and encoding_plan.hdr)
    cfg = _FlyConfig(
        interps=[interp],
        pins=pins,
        title_overlay=_render_title_overlay(title_text, width, height, hdr),
        width=width,
        height=height,
        dest_zoom=max(3.0, min(14.0, dz)),
        hdr=hdr,
    )
    progress = timing.schedule(duration, fps)
    title_in = max(1, round(_TITLE_FADE_SECONDS * fps))
    # The title rises with the take-off and stays: the hold is where it is read.
    alphas = [min(1.0, i / title_in) for i in range(len(progress))]

    _tile_cache.clear()
    rendered = _pipe_frames(cfg, output_path, progress, alphas, fps, encoding_plan)
    logger.info(
        "Map fly done: %d frames (%d rendered), %d tiles", len(progress), rendered, len(_tile_cache)
    )
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
) -> Path:
    """A location card: fly from the last place to this one, then hold on it with its name.

    Both ends sit at `_CARD_ZOOM`, wide enough that a 30 km hop keeps both towns in
    frame on a pan and a long one climbs out and back in. The name fades in as the
    camera lands and stays for the whole still hold.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    timing = timing or MapMoveTiming()
    w_card = width / (2.0**_CARD_ZOOM)
    start = (*_to_world(*came_from), w_card)
    end = (*_to_world(*destination), w_card)
    hdr = bool(encoding_plan and encoding_plan.hdr)
    cfg = _FlyConfig(
        interps=[_pick_interpolator(start, end, width)],
        pins=[_PinData(lat=destination[0], lon=destination[1])],
        title_overlay=_render_title_overlay(label, width, height, hdr, anchor=_CARD_LABEL_Y),
        width=width,
        height=height,
        dest_zoom=float(_CARD_ZOOM),
        hdr=hdr,
    )
    progress = timing.schedule(duration, fps)
    _tile_cache.clear()
    rendered = _pipe_frames(
        cfg, output_path, progress, timing.label_alphas(duration, fps), fps, encoding_plan
    )
    logger.info(
        "Map move card: %d frames (%d rendered), %d tiles, %.1fs",
        len(progress),
        rendered,
        len(_tile_cache),
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
    return lat, lon, max(float(_MIN_ZOOM_FLOOR), min(float(_CITY_ZOOM), zoom))


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
                logger.info("Map fly %d/%d (z=%.1f, %d tiles)", i, total, z, len(_tile_cache))

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
    from .map_renderer import _get_font

    is_portrait = h > w
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    fs = int(w * 0.12) if is_portrait else int(h * 0.09)
    font = _get_font(fs, bold=True)

    white = ceil_rgb_for_hdr((255, 255, 255)) if hdr else (255, 255, 255)
    lines = _wrap_text(text, draw, font, int(w * 0.88))
    line_h = int(fs * 1.2)
    total_h = line_h * len(lines)
    if anchor is None:
        anchor = 0.5 if is_portrait else 0.75
    block_y = int(h * anchor) - total_h // 2
    band_pad = int(fs * 0.8)
    _draw_gradient_band(draw, block_y - band_pad, total_h + 2 * band_pad, w, h)
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        x = (w - tw) // 2
        y = block_y + i * line_h
        draw.text((x + 2, y + 2), line, fill=(0, 0, 0, 130), font=font)
        draw.text((x, y), line, fill=(*white, 240), font=font)

    return img
