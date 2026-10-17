"""The feature suite's caption probe sees drawn text, not encoder noise (#2461, #2646).

The captions feature test compares a film with captions to the same film rendered without,
frame by frame, and reads how far the difference reaches across a band. Two encodes of
the same pictures are never bit-identical: a caption drawn elsewhere changes the encoder's
decisions, and on the real-Immich runs one pixel of one frame came out 27 grey levels
apart in a band with no caption in it. The probe read that pixel as a date. A caption's
letters change hundreds of pixels in strokes; the probe counts a pixel only when a
neighbour differs too.

That was half the fix. Encoder noise is not only single pixels: it sits along the encoder's
block edges, a few pixels side by side, and the same column 79 of the date band came out
more than 24 apart again on a later run. Measured on a captioned 720p film against the same
film without captions, bands no caption covers differ by at most 31 grey levels and a
caption's frames by at least 131, so a pixel now counts from 64 up.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from immich_memories.processing.clip_caption import ClipCaption, caption_filters, caption_font_path
from tests.integration.features.film_probe import differing_columns, grey_frame

_PICTURE = Path(__file__).parent / "e2e/fixtures/library/birthday-superheroes.jpg"
_DATE_BAND = "iw/2:ih*0.15:iw/2:ih*0.85"

_W, _H = 160, 90


def _frame(marks: dict[tuple[int, int], int] | None = None) -> bytes:
    pixels = bytearray([90] * (_W * _H))
    for (x, y), value in (marks or {}).items():
        pixels[y * _W + x] = value
    return bytes(pixels)


def test_one_pixel_of_encoder_noise_is_no_caption():
    plain = _frame()
    noisy = _frame({(79, 74): 90 + 27})

    assert differing_columns(plain, noisy) == 0.0


def test_a_caption_reaches_as_far_as_its_last_stroke():
    plain = _frame()
    # White text: strokes two columns wide with a gap between, the last one in column 64.
    text = {(x, y): 240 for x in range(10, 65) for y in range(40, 52) if x % 3}

    assert differing_columns(plain, _frame(text)) == 65 / _W


def test_a_one_pixel_wide_stroke_still_counts():
    plain = _frame()
    stroke = {(120, y): 240 for y in range(40, 44)}

    assert differing_columns(plain, _frame(stroke)) == 121 / _W


def test_noise_beside_a_caption_does_not_stretch_its_reach():
    plain = _frame()
    marks = {(x, y): 240 for x in range(10, 40) for y in range(40, 52)}
    marks[(150, 10)] = 90 + 30

    assert differing_columns(plain, _frame(marks)) == 40 / _W


def test_a_block_of_encoder_noise_at_the_measured_ceiling_is_no_caption():
    plain = _frame()
    # Two encodes apart along a block edge: neighbours, 31 grey levels off.
    block = {(x, y): 90 + 31 for x in (78, 79) for y in range(70, 76)}

    assert differing_columns(plain, _frame(block)) == 0.0


def _picture(tmp_path: Path, name: str, caption: ClipCaption | None) -> Path:
    out = tmp_path / f"{name}.png"
    filters = ["scale=1280:720", "setsar=1"]
    if caption is not None:
        filters += caption_filters(caption, 1280, 720, font_path=caption_font_path())
    subprocess.run(  # noqa: S603 -- fixed ffmpeg argv
        ["ffmpeg", "-v", "error", "-y", "-i", str(_PICTURE), "-vf", ",".join(filters),
         "-frames:v", "1", str(out)],
        check=True,
    )  # fmt: skip
    return out


def _ffmpeg_draws_text() -> bool:
    filters = subprocess.run(
        ["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True, check=False
    ).stdout
    return " drawtext " in filters


@pytest.mark.skipif(not _ffmpeg_draws_text(), reason="this FFmpeg has no drawtext (no libfreetype)")
def test_a_date_drawn_by_the_film_still_reaches_across_its_band(tmp_path):
    """The film's own date caption, on a busy picture, still reads as a caption."""
    bare = grey_frame(_picture(tmp_path, "bare", None), 0, band=_DATE_BAND)
    dated = grey_frame(
        _picture(tmp_path, "dated", ClipCaption(date="Saturday 5")), 0, band=_DATE_BAND
    )

    assert differing_columns(bare, dated) > 0.85
