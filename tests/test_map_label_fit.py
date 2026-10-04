"""A long place name shrinks to fit a portrait map card (#1954 cases 13, 14).

Owner ruling: a word wider than the safe width — "Saint-Jean-Cap-Ferrat", a
long Greek compound, a long Korean phrase — does not break on its own, so it
must shrink instead. Short names must render exactly as before.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from immich_memories.titles.map_renderer import (
    _draw_label_at,
    _fit_pin_label_font,
    _fit_title_lines,
    _get_font,
)

_FR = "Saint-Jean-Cap-Ferrat"
_GREEK = "Αγία Παρασκευή Λακωνίας"
_CYRILLIC = "Петропавловск-Камчатский"
_CJK = "乌鲁木齐天山天池国家地质公园"
_KOREAN = "제주특별자치도 서귀포시 성산일출봉"


def _draw() -> ImageDraw.ImageDraw:
    return ImageDraw.Draw(Image.new("RGBA", (10, 10)))


class TestFitTitleLines:
    def test_a_short_name_is_unchanged(self):
        draw = _draw()
        base_font = _get_font(120, bold=True)

        lines, font = _fit_title_lines(_FR, draw, base_size=120, bold=True, max_width=10_000)

        assert lines == [_FR]
        assert getattr(font, "size", None) == getattr(base_font, "size", None)

    def test_a_long_hyphenated_name_shrinks_to_fit_a_portrait_card(self):
        draw = _draw()
        max_width = 1080 * 0.88  # portrait card safe width (6% margin each side)

        lines, font = _fit_title_lines(_FR, draw, base_size=130, bold=True, max_width=max_width)

        widths = [draw.textbbox((0, 0), line, font=font)[2] for line in lines]
        assert max(widths) <= max_width
        assert font.size < 130  # it actually shrank, not just wrapped

    def test_never_shrinks_below_the_floor(self):
        draw = _draw()

        _, font = _fit_title_lines(_CJK, draw, base_size=130, bold=True, max_width=50, min_size=18)

        assert font.size >= 18

    def test_at_most_two_lines(self):
        draw = _draw()

        lines, _ = _fit_title_lines(
            "one two three four five six seven", draw, base_size=60, bold=True, max_width=10
        )

        assert len(lines) <= 2

    def test_a_long_multi_word_french_name_keeps_every_word(self):
        """Regression: the fit check used to slice to `max_lines` before measuring
        width, so a name that wrapped to 3+ lines at the base size silently lost
        every word past the second line instead of shrinking further.
        """
        draw = _draw()
        text = "La Chapelle-Saint-Mesmin Loiret Centre-Val de Loire"
        max_width = 1080 * 0.88

        lines, font = _fit_title_lines(text, draw, base_size=130, bold=True, max_width=max_width)

        rendered_words = " ".join(lines).replace("…", "").split()
        assert set(rendered_words) == set(text.split())
        widths = [draw.textbbox((0, 0), line, font=font)[2] for line in lines]
        assert max(widths) <= max_width

    def test_a_trailing_comma_from_word_wrap_is_stripped(self):
        """A region name wrapped away from its city leaves a dangling comma
        on the city's line — it reads as unfinished, so it is dropped.
        """
        draw = _draw()
        text = "Petite ville de Bourg-en-Bresse, Auvergne-Rhône-Alpes"
        max_width = 1080 * 0.88

        lines, _ = _fit_title_lines(text, draw, base_size=130, bold=True, max_width=max_width)

        assert not any(line.endswith(",") for line in lines)
        rendered_words = " ".join(lines).replace(",", "").split()
        assert set(rendered_words) == set(text.replace(",", "").split())

    def test_a_long_hyphenated_word_breaks_at_a_hyphen_before_shrinking_far(self):
        """Below 75% of the base size, a line still too wide breaks at a hyphen
        instead of shrinking all the way down to fit as one unbroken word —
        it reads better larger than tiny-but-whole.
        """
        draw = _draw()
        max_width = 1080 * 0.88

        lines, font = _fit_title_lines(_FR, draw, base_size=130, bold=True, max_width=max_width)

        assert any(line.endswith("-") for line in lines)
        # Breaking at a hyphen keeps the font well above the 18px floor.
        assert font.size > 18

    def test_a_pathological_name_truncates_with_an_ellipsis_not_silently(self):
        """At the font floor, a name that still does not fit in `max_lines` is
        marked as cut — never just dropped without a trace.
        """
        draw = _draw()
        text = "one two three four five six seven eight nine ten eleven twelve"

        lines, _ = _fit_title_lines(text, draw, base_size=20, bold=True, max_width=40, min_size=18)

        assert len(lines) <= 2
        assert lines[-1].endswith("…")


class TestFitTitleLinesOtherScripts:
    def test_greek_fits_a_portrait_card(self):
        draw = _draw()
        max_width = 1080 * 0.88

        lines, font = _fit_title_lines(_GREEK, draw, base_size=130, bold=True, max_width=max_width)

        widths = [draw.textbbox((0, 0), line, font=font)[2] for line in lines]
        assert max(widths) <= max_width

    def test_cyrillic_fits_a_portrait_card(self):
        draw = _draw()
        max_width = 1080 * 0.88

        lines, font = _fit_title_lines(
            _CYRILLIC, draw, base_size=130, bold=True, max_width=max_width
        )

        widths = [draw.textbbox((0, 0), line, font=font)[2] for line in lines]
        assert max(widths) <= max_width

    def test_korean_fits_a_portrait_card(self):
        draw = _draw()
        max_width = 1080 * 0.88

        lines, font = _fit_title_lines(_KOREAN, draw, base_size=130, bold=True, max_width=max_width)

        widths = [draw.textbbox((0, 0), line, font=font)[2] for line in lines]
        assert max(widths) <= max_width


class TestFitPinLabelFont:
    def test_a_short_label_is_unchanged(self):
        draw = _draw()

        font, width = _fit_pin_label_font("Paris", draw, base_size=40, max_width=10_000)

        assert font.size == 40
        assert width == draw.textbbox((0, 0), "Paris", font=font)[2]

    def test_a_long_label_shrinks_to_fit(self):
        draw = _draw()

        font, width = _fit_pin_label_font(_CYRILLIC, draw, base_size=40, max_width=300)

        assert width <= 300
        assert font.size < 40

    def test_never_shrinks_below_the_floor(self):
        draw = _draw()

        font, _ = _fit_pin_label_font(_CJK, draw, base_size=40, max_width=5, min_size=10)

        assert font.size >= 10


class TestDrawLabelAtStaticMapFallback:
    """`render_trip_map_array` draws labels through `_draw_label_at`, which
    flipped a label past the right edge to a left-side position with no
    floor check — a long name near a narrow frame's edge went negative (#1954).
    """

    def test_a_long_label_near_the_edge_stays_inside_the_frame(self):
        width, height = 200, 200
        name = "Saint-Jean-Cap-Ferrat, Alpes-Maritimes, France"

        img = Image.new("RGBA", (width, height), (20, 20, 20, 255))
        draw = ImageDraw.Draw(img)
        font = _get_font(12, bold=False)

        _draw_label_at(draw, name, px=width - 2, py=90, width=width, height=height, font=font)

        arr = np.asarray(img)
        margin = 3
        edge = np.concatenate([arr[:, :margin, :3], arr[:, -margin:, :3]], axis=1)
        assert edge.max() < 100, "Label near a narrow frame's edge overflowed it"

    def test_a_pin_near_the_top_does_not_push_the_label_off_the_top(self):
        width, height = 1080, 1920
        font = _get_font(max(12, int(min(width, height) * 0.018)), bold=False)

        img = Image.new("RGBA", (width, height), (20, 20, 20, 255))
        draw = ImageDraw.Draw(img)
        _draw_label_at(draw, "Nice", px=500, py=2, width=width, height=height, font=font)

        arr = np.asarray(img)
        margin = 3
        top_rows = arr[:margin, :, :3]
        assert top_rows.max() < 100, "Label near the top edge overflowed it"
