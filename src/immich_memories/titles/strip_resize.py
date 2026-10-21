"""One horizontal strip of a Lanczos resize, equal to the same rows of the whole-frame resize."""

from __future__ import annotations

import math

from PIL import Image

_LANCZOS_SUPPORT = 3.0
# Image.resize premultiplies alpha around its passes; two separate calls would round it twice.
_PREMULTIPLIED = {"RGBA": "RGBa", "LA": "La"}


def _vertical_first(in_w: int, in_h: int, out_w: int, out_h: int) -> bool:
    # Pillow's own rule (13.0.0, Resample.c): it runs the vertical pass first when the height
    # shrinks by more than twice what the width does. The passes round to 8 bits in between, so
    # the order changes pixels; a strip must follow the order Pillow picks for the whole frame.
    return in_h - out_h > 0 and in_h - out_h > (in_w - out_w) * 2


def lanczos_strip(
    image: Image.Image, width: int, height: int, top: int, bottom: int
) -> Image.Image:
    """Rows ``top``..``bottom`` of ``image.resize((width, height), LANCZOS)``.

    Each pass runs on its own, so Pillow cannot choose a pass order for the strip that the whole
    frame would not use: from 13.0.0 a strip of a tall source otherwise runs vertical-first and
    differs from the whole-frame resize by up to 47 levels on noise.
    """
    if image.mode in _PREMULTIPLIED:
        strip = lanczos_strip(image.convert(_PREMULTIPLIED[image.mode]), width, height, top, bottom)
        return strip.convert(image.mode)
    lanczos = Image.Resampling.LANCZOS
    scale_y = image.height / height
    src_top, src_bottom = top * scale_y, bottom * scale_y
    if _vertical_first(image.width, image.height, width, height):
        rows = image.resize(
            (image.width, bottom - top), lanczos, box=(0, src_top, image.width, src_bottom)
        )
        return rows.resize((width, bottom - top), lanczos)
    # Horizontal first: resize only the source rows the strip's filter reaches. Rows past the
    # filter support carry zero weight, so the crop does not change a pixel.
    margin = math.ceil(_LANCZOS_SUPPORT * max(scale_y, 1.0)) + 2
    first = max(0, math.floor(src_top) - margin)
    last = min(image.height, math.ceil(src_bottom) + margin)
    rows = image.crop((0, first, image.width, last)).resize((width, last - first), lanczos)
    return rows.resize(
        (width, bottom - top), lanczos, box=(0, src_top - first, width, src_bottom - first)
    )
