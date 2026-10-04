"""A long place name shrinks to fit a portrait map card (#1954 cases 13, 14).

Owner ruling: a word wider than the safe width — "Saint-Jean-Cap-Ferrat", a
long Greek compound, a long Korean phrase — does not break on its own, so it
must shrink instead. Short names must render exactly as before.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from immich_memories.titles.map_renderer import (
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
