"""Trip map rendering — staticmap tiles + PIL text overlay.

Renders map tiles with big location pins + city labels, produces PIL Images
or numpy arrays ready for the GPU pipeline.
"""

from __future__ import annotations

import contextlib
import logging

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from staticmap import CircleMarker, StaticMap

logger = logging.getLogger(__name__)

# Map styling constants
_PIN_COLOR = "#E85D4A"
_PIN_SIZE = 16
_PIN_OUTLINE_COLOR = "#FFFFFF"
_PIN_OUTLINE_SIZE = 20
_LABEL_COLOR = (255, 255, 255, 190)  # Semi-transparent white
_LABEL_SHADOW_COLOR = (0, 0, 0, 80)  # Very subtle shadow
_OSM_ATTRIBUTION = "\u00a9 OpenStreetMap contributors"

# Tile URL templates — only providers that work without API keys.
MAP_STYLES: dict[str, str] = {
    "osm": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    "topo": "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
    "satellite": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
}
DEFAULT_MAP_STYLE = "satellite"


def render_trip_map_array(
    locations: list[tuple[float, float]],
    width: int = 1920,
    height: int = 1080,
    location_names: list[str] | None = None,
    map_style: str = DEFAULT_MAP_STYLE,
) -> np.ndarray:
    """Render map as numpy float32 array for the GPU pipeline.

    Returns array normalized to [0, 1] range, shape (height, width, 3).
    Includes pins and city labels but no title (title rendered by GPU).
    """
    base_map, sm = _render_base_map(locations, width, height, map_style)

    if location_names and sm is not None:
        _draw_pin_labels(base_map, locations, location_names, sm)

    _add_attribution(base_map, width, height)
    arr = np.array(base_map, dtype=np.float32) / 255.0
    return arr


def render_location_card(
    location_name: str,
    width: int = 1920,
    height: int = 1080,
    lat: float | None = None,
    lon: float | None = None,
    map_style: str = DEFAULT_MAP_STYLE,
) -> Image.Image:
    """Render a location card background (no text).

    If lat/lon provided, renders a zoomed satellite map.
    Otherwise falls back to dark gradient.

    Text is rendered by the title video pipeline, not baked into the
    background — baking text caused a ghost echo (#83).
    """
    if lat is not None and lon is not None:
        img, _sm = _render_base_map([(lat, lon)], width, height, map_style)
        # Darken the map so text pops
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 100))
        img_rgba = img.convert("RGBA")
        img = Image.alpha_composite(img_rgba, overlay).convert("RGB")
    else:
        img = Image.new("RGB", (width, height), color=(30, 30, 35))

    return img


# ---------------------------------------------------------------------------
# Internal rendering helpers
# ---------------------------------------------------------------------------


def _render_base_map(
    locations: list[tuple[float, float]],
    width: int,
    height: int,
    map_style: str = DEFAULT_MAP_STYLE,
) -> tuple[Image.Image, StaticMap | None]:
    """Render map tiles with big location pins. Returns (image, StaticMap)."""
    url_template = MAP_STYLES.get(map_style, MAP_STYLES[DEFAULT_MAP_STYLE])
    m = StaticMap(width, height, url_template=url_template)

    for lat, lon in locations:
        m.add_marker(CircleMarker((lon, lat), _PIN_OUTLINE_COLOR, _PIN_OUTLINE_SIZE))
        m.add_marker(CircleMarker((lon, lat), _PIN_COLOR, _PIN_SIZE))

    try:
        image = m.render()
    except Exception as e:  # noqa: BLE001 -- see _render_satellite: same transport
        logger.warning("Map tile fetch failed, using solid background: %s", e)
        image = Image.new("RGB", (width, height), color=(40, 50, 60))
        return image, None

    if image.size != (width, height):
        image = image.resize((width, height))

    return image, m


def _draw_pin_labels(
    image: Image.Image,
    locations: list[tuple[float, float]],
    names: list[str],
    sm: StaticMap,
) -> None:
    """Draw city name labels next to each pin, blended with the map."""
    if not locations or not names:
        return

    w, h = image.size
    label_size = max(12, int(min(w, h) * 0.018))
    font = _get_font(label_size, bold=False)

    # Draw labels on RGBA overlay for semi-transparent blending
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    for (lat, lon), name in zip(locations, names, strict=False):
        px, py = _geo_to_pixel(lat, lon, sm)
        px = max(5, min(w - 5, px))
        py = max(5, min(h - 5, py))
        _draw_label_at(draw, name, px, py, w, h, font)

    # Composite the semi-transparent labels onto the map
    image_rgba = image.convert("RGBA")
    composited = Image.alpha_composite(image_rgba, overlay)
    image.paste(composited.convert("RGB"))


def _geo_to_pixel(lat: float, lon: float, sm: StaticMap) -> tuple[int, int]:
    """Convert (lat, lon) to pixel coordinates using staticmap internals."""
    from staticmap.staticmap import _lat_to_y, _lon_to_x

    x_tile = _lon_to_x(lon, sm.zoom)
    y_tile = _lat_to_y(lat, sm.zoom)

    px = sm._x_to_px(x_tile)
    py = sm._y_to_px(y_tile)

    return px, py


def _draw_label_at(draw, name: str, px: int, py: int, width: int, height: int, font) -> None:
    """Draw a single city label near a pin, shrunk and clamped to stay in frame (#1954)."""
    offset_x = int(width * 0.015)
    offset_y = int(-height * 0.012)
    margin = max(10, int(width * 0.02))
    min_size = max(6, int(width * _MIN_PIN_LABEL_PX / 1080))
    base_size = getattr(font, "size", 14)
    font, text_w = _fit_pin_label_font(name, draw, base_size, width - 2 * margin, min_size=min_size)

    lx = px + offset_x
    ly = py + offset_y

    # If label would go off right edge, place it to the left of the pin instead
    if lx + text_w > width - margin:
        lx = px - offset_x - text_w
    lx = max(margin, min(width - margin - text_w, lx))
    ly = max(margin, min(height - margin, ly))

    # Shadow for readability (2px offset)
    draw.text((lx + 2, ly + 2), name, fill=_LABEL_SHADOW_COLOR, font=font)
    draw.text((lx, ly), name, fill=_LABEL_COLOR, font=font)


def _add_attribution(image: Image.Image, width: int, height: int) -> None:
    """Add OSM attribution text in bottom-right corner."""
    draw = ImageDraw.Draw(image)
    font_size = max(10, int(height * 0.015))
    font = _get_font(font_size)
    bbox = draw.textbbox((0, 0), _OSM_ATTRIBUTION, font=font)
    text_w = bbox[2] - bbox[0]
    x = width - text_w - 10
    y = height - font_size - 8
    draw.text((x, y), _OSM_ATTRIBUTION, fill=(200, 200, 200), font=font)


def _get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a font at the given size, preferring Montserrat (OFL).

    The wheel carries Montserrat, so the pin labels never needed a download;
    the user's own font directory still overrides it. A letter Montserrat
    lacks, such as in a Greek place name, comes from the Noto chain (#1101).
    """
    from pathlib import Path

    from immich_memories.titles.font_chain import title_font
    from immich_memories.titles.fonts import FontWeight, bundled_font_path

    weight: FontWeight = "Bold" if bold else "Regular"
    cached = Path.home() / ".immich-memories" / "fonts" / "Montserrat" / f"Montserrat-{weight}.ttf"
    for montserrat in (bundled_font_path("Montserrat", weight), cached):
        if montserrat is not None and montserrat.exists():
            with contextlib.suppress(OSError):
                return title_font(montserrat, size, bold=bold)

    # System fallbacks
    fallbacks = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in fallbacks:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap_text(
    text: str,
    draw: ImageDraw.ImageDraw,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_w: int,
) -> list[str]:
    """Word-wrap text to fit within max_w pixels."""
    if "," in text:
        parts = [p.strip() for p in text.split(",", 1)]
        if all(draw.textbbox((0, 0), p, font=font)[2] <= max_w for p in parts):
            return parts
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        if draw.textbbox((0, 0), test, font=font)[2] > max_w and current:
            lines.append(current)
            current = word
        else:
            current = test
    if current:
        lines.append(current)
    return lines or [text]


# A long place name ("Saint-Jean-Cap-Ferrat", a Greek compound, a CJK string)
# can still be one unbroken token after wrapping: the floor these two helpers
# shrink down to before they give up and let it overflow slightly.
_MIN_CARD_FONT_PX = 18
_MIN_PIN_LABEL_PX = 10
# Below this fraction of the base size, break long hyphenated words at a
# hyphen instead of shrinking further — it reads better than a tiny font.
_HYPHEN_BREAK_FACTOR = 0.75


def _fit_title_lines(
    text: str,
    draw: ImageDraw.ImageDraw,
    base_size: int,
    bold: bool,
    max_width: int,
    min_size: int = _MIN_CARD_FONT_PX,
    max_lines: int = 2,
) -> tuple[list[str], ImageFont.FreeTypeFont | ImageFont.ImageFont]:
    """Wrap a title at spaces/the first comma, then shrink until it fully fits.

    `_wrap_text` only breaks on spaces or a comma, so one word wider than
    `max_width` — a long compound place name — stays whole and overflows a
    fixed-size card. The fit check always re-wraps the full text at the
    current size: a line count or width that only looks right on a slice of
    the lines dropped words silently, so both must hold on the whole
    wrapped result. Below `_HYPHEN_BREAK_FACTOR` of `base_size`, a line still
    too wide also gets broken at a hyphen before shrinking further. Widths
    are measured with the actual font via `textbbox` so CJK, Greek and
    Cyrillic names shrink by their real width, not a Latin-average guess.

    `min_size` is a floor. Below it, this stops shrinking; if the text still
    does not fit in `max_lines`, the overflow is folded into the last line
    with an ellipsis — truncated visibly, never dropped without a trace.
    """
    size = base_size
    hyphen_threshold = int(base_size * _HYPHEN_BREAK_FACTOR)
    font = _get_font(size, bold=bold)
    lines = _wrap_text(text, draw, font, max_width)
    while True:
        font = _get_font(size, bold=bold)
        lines = _wrap_text(text, draw, font, max_width)
        if size <= hyphen_threshold:
            lines = _break_hyphenated_lines(lines, draw, font, max_width)
        widths = [draw.textbbox((0, 0), line, font=font)[2] for line in lines]
        fits = len(lines) <= max_lines and (not widths or max(widths) <= max_width)
        if fits or size <= min_size:
            break
        size = max(min_size, int(size * 0.92))
    if len(lines) > max_lines:
        lines = _truncate_with_ellipsis(lines, draw, font, max_width, max_lines)
    return [_strip_trailing_comma(line) for line in lines], font


def _break_hyphenated_lines(
    lines: list[str],
    draw: ImageDraw.ImageDraw,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    """Break any line still too wide at a hyphen, keeping the hyphen on the first part."""
    result: list[str] = []
    for line in lines:
        width = draw.textbbox((0, 0), line, font=font)[2]
        if width <= max_width or "-" not in line:
            result.append(line)
        else:
            result.extend(_hyphen_wrap(line, draw, font, max_width))
    return result


def _hyphen_wrap(
    word: str,
    draw: ImageDraw.ImageDraw,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_w: int,
) -> list[str]:
    """Split a hyphenated word into the widest chunks that fit, keeping each hyphen."""
    parts = word.split("-")
    chunks: list[str] = []
    current = parts[0]
    for part in parts[1:]:
        candidate = f"{current}-{part}"
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_w:
            current = candidate
        else:
            chunks.append(f"{current}-")
            current = part
    chunks.append(current)
    return chunks


def _truncate_with_ellipsis(
    lines: list[str],
    draw: ImageDraw.ImageDraw,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
    max_lines: int,
) -> list[str]:
    """Fold everything past `max_lines` into the last line, marked with an ellipsis.

    Only reached at the font floor: shrinking further would make the label
    illegible, so instead of silently losing the rest of the name, the cut
    is made visible.
    """
    kept = lines[:max_lines].copy()
    remainder = " ".join(lines[max_lines:])
    last = f"{kept[-1]} {remainder}".strip()
    while last and draw.textbbox((0, 0), f"{last}…", font=font)[2] > max_width:
        last = last[:-1].rstrip()
    kept[-1] = f"{last}…" if last else "…"
    return kept


def _strip_trailing_comma(line: str) -> str:
    """Drop a comma left dangling at a wrapped line's end — it reads as unfinished."""
    return line.removesuffix(",")


def _fit_pin_label_font(
    text: str,
    draw: ImageDraw.ImageDraw,
    base_size: int,
    max_width: int,
    min_size: int = _MIN_PIN_LABEL_PX,
) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, int]:
    """Shrink a single-line pin label until its measured width fits `max_width`.

    Pin labels never wrap — there is no room for a second line next to a
    pin — so this only shrinks, returning the font and its measured width so
    the caller can also clamp the label's x position inside the frame.
    """
    size = base_size
    while True:
        font = _get_font(size, bold=True)
        width = int(draw.textbbox((0, 0), text, font=font)[2])
        if width <= max_width or size <= min_size:
            return font, width
        size = max(min_size, int(size * 0.9))


def _draw_gradient_band(draw: ImageDraw.ImageDraw, y: int, bh: int, w: int, h: int) -> None:
    """Soft dark gradient band for text readability."""
    cy, half = y + bh // 2, bh // 2
    for dy in range(-half, half + 1):
        row = cy + dy
        if 0 <= row < h:
            a = int(100 * (1 - (abs(dy) / max(1, half)) ** 2))
            draw.line([(0, row), (w, row)], fill=(0, 0, 0, a))


def _overlay_composite(frame: Image.Image, ov: Image.Image, alpha: float) -> Image.Image:
    """Composite RGBA overlay onto RGB frame with given opacity."""
    import numpy as np

    if alpha >= 0.99:
        return Image.alpha_composite(frame.convert("RGBA"), ov).convert("RGB")
    arr = np.array(ov.copy())
    arr[:, :, 3] = (arr[:, :, 3].astype(np.float32) * alpha).astype(np.uint8)
    return Image.alpha_composite(
        frame.convert("RGBA"),
        Image.fromarray(arr, "RGBA"),
    ).convert("RGB")
