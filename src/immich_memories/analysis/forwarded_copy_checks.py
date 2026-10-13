"""What refuses a forwarded copy that would otherwise stand in: not a picture of this life.

A forwarded copy (`forwarded_fallback`) is a picture somebody sent. Three kinds of them are no
moment of the period, whatever their people:

- a composed picture: a collage app's tiles under a text title, a cut-out on a made-up
  background, a poster. Its caption says so ("a collage of photos"), or its pixels do: thin
  flat gutters running between textured tiles, across and down, which an ordinary photograph
  does not have;
- a copy of a picture the library already holds (`forwarded_fallback`, by preview hash).

Captions are read only where the run has them (a model reader); the gutter check reads pixels.
"""

from __future__ import annotations

import io
import re

import numpy as np

# Words a caption uses for a picture made rather than taken, in the languages captions come in.
_COMPOSED = re.compile(
    r"\b(collage|montage|composite|superimposed|photoshopped|edited image|graphic design"
    r"|grid of (?:photos|pictures|images)|text overlay|poster|meme|sticker|clip ?art"
    r"|illustration|cartoon|drawing|photomontage|mosaïque|mosaique|assemblage)\b",
    re.IGNORECASE,
)
# The gutter check's working width, and what a gutter is there: a line at most this thin, this
# flat, the page's own white or black, between neighbours this textured on both sides. A painted
# facade has flat bands too, but thicker and coloured.
_WIDTH = 512
_GUTTER_SHARE = 0.03
_FLAT_STD = 8.0
_TEXTURED_STD = 20.0
_EDGE_SHARE = 0.03
_PAGE_DARK, _PAGE_LIGHT = 35.0, 220.0


def composed_in_words(line: str) -> str | None:
    """The caption word that says a picture was made rather than taken, if the line has one."""
    found = _COMPOSED.search(line)
    return found.group(1).lower() if found else None


def looks_composed(image: bytes) -> bool:
    """Whether a preview is a collage: flat gutters between textured tiles, across and down.

    A gutter each way: tiles side by side and one above the other. A gutter may run across half the picture only (a
    collage's two columns of tiles rarely line up), so each half is read on its own. A sky above
    a horizon is flat on one side only, and a wall is no thin line between two tiles, so a
    photograph passes.
    """
    pixels = _gray(image)
    if pixels is None:
        return False
    across = _gutters(pixels)
    down = _gutters(pixels.T)
    return across >= 1 and down >= 1


def _gray(image: bytes) -> np.ndarray | None:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(image)) as opened:
            gray = opened.convert("L")
            height = max(1, round(gray.height * _WIDTH / max(1, gray.width)))
            return np.asarray(gray.resize((_WIDTH, height)), dtype=np.float32)
    except (OSError, UnidentifiedImageError, ValueError):
        return None


def _gutters(pixels: np.ndarray) -> int:
    """The gutters running across `pixels`, read on each half of every row: distinct runs."""
    half = pixels.shape[1] // 2
    found = _gutter_rows(pixels[:, :half]) | _gutter_rows(pixels[:, half:])
    return len(found)


def _gutter_rows(pixels: np.ndarray) -> set[int]:
    """Where thin flat runs of rows sit with textured rows right above and below, edges left out."""
    rows = pixels.shape[0]
    spread = pixels.std(axis=1)
    level = pixels.mean(axis=1)
    flat = (spread < _FLAT_STD) & ((level > _PAGE_LIGHT) | (level < _PAGE_DARK))
    edge = max(1, int(rows * _EDGE_SHARE))
    thin = max(2, int(rows * _GUTTER_SHARE))
    found: set[int] = set()
    index = edge
    while index < rows - edge:
        if not flat[index]:
            index += 1
            continue
        end = index
        while end < rows and flat[end]:
            end += 1
        if (
            end - index <= thin
            and index - 1 >= edge
            and end < rows - edge
            and spread[max(0, index - 3) : index].mean() > _TEXTURED_STD
            and spread[end : end + 3].mean() > _TEXTURED_STD
        ):
            found.add((index + end) // 2 // thin)
        index = end
    return found
