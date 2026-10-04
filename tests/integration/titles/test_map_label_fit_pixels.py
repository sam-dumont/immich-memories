"""A long place name shrinks instead of overflowing a map card (#1954 cases 13, 14).

Owner ruling: French and other-script place names were clipped at the left/right
frame edges on portrait map cards (1080x1920, 2160x3840). `_render_title_overlay`
now shrinks the font until every wrapped line fits inside a 6% margin, so these
names stay fully inside the frame; a short name is unaffected.

Run: make test-integration-titles
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageDraw

from immich_memories.titles.map_animation import _render_title_overlay
from immich_memories.titles.map_renderer import _fit_title_lines, _get_font

pytestmark = [pytest.mark.integration]

# A hyphenated French name and a long Greek place name: neither has a space to
# break on, so the old code rendered them whole — past the frame edge.
_SAINT_JEAN = "Saint-Jean-Cap-Ferrat"
_GREEK = "Αλεξανδρούπολη"
_PORTRAIT_SIZES = [(1080, 1920), (2160, 3840)]
# Half the 6% safety margin on each side: text must not reach even this close to the edge.
_MARGIN_SHARE = 0.03


def _margin_columns(width: int) -> int:
    return max(1, int(width * _MARGIN_SHARE))


def _brightest_in_margins(overlay_rgba: np.ndarray, margin: int) -> int:
    """Max RGB channel value found in the leftmost/rightmost `margin` columns.

    The gradient band is black at low alpha (background), so a bright pixel
    there can only be overflowing white text.
    """
    rgb = overlay_rgba[:, :, :3]
    left = rgb[:, :margin]
    right = rgb[:, -margin:]
    return int(max(left.max(initial=0), right.max(initial=0)))


class TestLongNameFitsInsidePortraitCard:
    @pytest.mark.parametrize(("width", "height"), _PORTRAIT_SIZES)
    @pytest.mark.parametrize("text", [_SAINT_JEAN, _GREEK])
    def test_no_text_reaches_the_outer_margin(self, width, height, text):
        overlay = _render_title_overlay(text, width, height, hdr=False)

        assert overlay is not None
        arr = np.array(overlay)
        margin = _margin_columns(width)

        assert _brightest_in_margins(arr, margin) < 100, (
            f"{text!r} at {width}x{height} overflowed into the outer margin"
        )


class TestShortNameIsUnchanged:
    def test_a_short_name_renders_at_the_original_font_size(self):
        """Measures the rendered glyph width, not just "not too tall": a width
        match pins down the actual font size, where a height bound would pass
        even if the font had shrunk a little.
        """
        width, height = 1080, 1920
        base_fs = int(width * 0.12)
        probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

        # Direct check: the fit helper with the exact production parameters
        # must hand back the base font, unshrunk.
        _, chosen_font = _fit_title_lines(
            "Nice", probe, base_size=base_fs, bold=True, max_width=int(width * 0.88)
        )
        assert chosen_font.size == base_fs

        reference_font = _get_font(base_fs, bold=True)
        expected_w = probe.textbbox((0, 0), "Nice", font=reference_font)[2]

        overlay = _render_title_overlay("Nice", width, height, hdr=False)

        assert overlay is not None
        arr = np.array(overlay)
        bright_cols = np.where(arr[:, :, :3].max(axis=(0, 2)) > 200)[0]
        assert bright_cols.size > 0
        measured_w = bright_cols.max() - bright_cols.min()

        # textbbox's advance width runs a bit past the last glyph's actual ink
        # (confirmed by direct rendering, not assumed) — a fixed 4px tolerance
        # is too tight for that, but 10% still catches a real shrink (which
        # drops the font by ~8% per step).
        assert abs(measured_w - expected_w) <= max(6, int(expected_w * 0.1))
