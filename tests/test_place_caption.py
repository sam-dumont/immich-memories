"""Place names in the per-clip caption (#313, reworked in #464/#465).

`AssemblyClip.location_name` is already populated from Immich EXIF as
"City, Country". Escaping is mandatory: a colon separates drawtext's own
options, so an unescaped place name does not merely look wrong, it fails the
filter graph. Timeline semantics (dedupe, date wording) live in
test_caption_timeline.py.
"""

from __future__ import annotations

from pathlib import Path

from immich_memories.processing.assembly_config import AssemblyClip
from immich_memories.processing.clip_caption import (
    ClipCaption,
    caption_filters,
    captions_for_timeline,
)


def _clip(date: str | None = "2026-01-05", place: str | None = None) -> AssemblyClip:
    return AssemblyClip(
        path=Path("/x.mp4"), duration=4.0, date=date, asset_id="x", location_name=place
    )


def _place_filter(text: str) -> str:
    (only,) = caption_filters(ClipCaption(place=text), 1920, 1080)
    return only


class TestPlaceInTheCaption:
    def test_place_is_shown_when_asked_for(self):
        (caption,) = captions_for_timeline([_clip(place="Paris, France")], place=True)

        assert caption.place == "Paris, France"

    def test_place_is_left_out_unless_asked_for(self):
        (caption,) = captions_for_timeline([_clip(place="Paris, France")])

        assert caption.place == ""

    def test_a_clip_without_a_place_still_captions_its_date(self):
        (caption,) = captions_for_timeline([_clip(place=None)], place=True)

        assert caption.place == "" and caption.date != ""

    def test_place_alone_when_the_clip_has_no_date(self):
        (caption,) = captions_for_timeline([_clip(date=None, place="Paris, France")], place=True)

        assert caption.place == "Paris, France" and caption.date == ""


class TestEscaping:
    """drawtext parses its own options out of the value; a raw colon breaks it."""

    def test_a_colon_is_escaped(self):
        assert "\\:" in _place_filter("Tel Aviv: Yafo")

    def test_an_apostrophe_survives_as_a_typographic_one(self):
        """Measured: drawtext drops an ASCII apostrophe however it is escaped,
        rendering "LAquila". U+2019 is the only form that reaches the screen."""
        out = _place_filter("L'Aquila")

        assert "L\u2019AQUILA" in out
        assert "L'AQUILA" not in out

    def test_a_backslash_is_escaped_before_anything_else(self):
        """Escaping backslash last would double-escape what came before it."""
        assert "\\\\" in _place_filter("a\\b")


class TestPlaceFitsTheFrame:
    """A long place shrinks, then shortens, so it never runs off the frame (#2637)."""

    # Long enough to overflow a portrait frame at the caption size, short enough for landscape.
    LONG = "Arrondissement de Ménara, Marruecos"
    # Too long even once shrunk: only an ellipsis keeps it inside a portrait frame.
    VERY_LONG = "Ouahat Sidi Brahim, Arrondissement de Ménara, Marrakech-Safi, Marruecos"

    @staticmethod
    def _drawn(text: str, width: int, height: int) -> tuple[str, int]:
        import re

        from immich_memories.processing.clip_caption import caption_font_path

        (only,) = caption_filters(
            ClipCaption(place=text), width, height, font_path=caption_font_path()
        )
        size = int(re.search(r":fontsize=(\d+)", only).group(1))
        shown = re.search(r"text='(.*?)'", only).group(1)
        return shown, size

    @staticmethod
    def _width(text: str, size: int) -> int:
        from immich_memories.processing.caption_image import CaptionStyle, text_width
        from immich_memories.processing.clip_caption import caption_font_path

        return text_width(text, CaptionStyle(caption_font_path(), size, (255, 255, 255), 2, 1))

    def test_a_long_place_shrinks_inside_a_portrait_frame(self):
        shown, size = self._drawn(self.LONG, 1080, 1920)
        inset = round(1080 * 0.055)

        assert shown == self.LONG.upper()  # shrunk, not shortened
        assert size < round(1080 * 0.0444)
        assert self._width(shown, size) <= 1080 - 2 * inset

    def test_the_same_place_keeps_its_size_in_landscape(self):
        shown, size = self._drawn(self.LONG, 1920, 1080)

        assert shown == self.LONG.upper()
        assert size == round(1080 * 0.0444)

    def test_a_place_too_long_to_shrink_is_shortened_last(self):
        shown, size = self._drawn(self.VERY_LONG, 1080, 1920)
        inset = round(1080 * 0.055)

        assert shown.endswith("…")
        assert size == round(round(1080 * 0.0444) * 0.6)
        assert self._width(shown, size) <= 1080 - 2 * inset
