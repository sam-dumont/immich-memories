"""A location card's name shrinks to the safe margin even when it is long (#1954).

Location cards draw their text through the generic title pipeline
(`renderer_pil.py`), not the map overlay fixed by #1954 — this only verifies
that pipeline already clears the same bar, rather than assuming it from
reading `_render_text_element`'s shrink loop.
"""

from __future__ import annotations

import numpy as np

from immich_memories.titles.renderer_pil import render_title_frame
from immich_memories.titles.safe_zones import safe_margin_ratio
from immich_memories.titles.styles import PRESET_STYLES

_STYLE = PRESET_STYLES["modern_warm"]
_PORTRAIT = (1080, 1920)


def _margin_columns(width: int, height: int) -> int:
    return int(width * safe_margin_ratio(width, height))


class TestLocationCardLongNameInPortrait:
    def test_a_long_hyphenated_name_stays_inside_the_safe_margin(self):
        width, height = _PORTRAIT
        name = "Saint-Jean-Cap-Ferrat-sur-Mer-et-Montagne-Alpes-Maritimes"

        frame = render_title_frame(name, None, _STYLE, width, height, animation_progress=1.0)

        margin = _margin_columns(width, height)
        edge_pixels = np.concatenate([frame[:, :margin], frame[:, -margin:]], axis=1)
        assert edge_pixels.max() < 200, "Location card text overflowed the safe margin"

    def test_a_short_name_is_unaffected(self):
        width, height = _PORTRAIT

        frame = render_title_frame("Nice", None, _STYLE, width, height, animation_progress=1.0)

        margin = _margin_columns(width, height)
        edge_pixels = np.concatenate([frame[:, :margin], frame[:, -margin:]], axis=1)
        assert edge_pixels.max() < 200
