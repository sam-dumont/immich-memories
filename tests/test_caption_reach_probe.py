"""The feature suite's caption probe sees drawn text, not one pixel of encoder noise (#2461).

The captions feature test compares a film with captions to the same film rendered without,
frame by frame, and reads how far the difference reaches across a band. Two encodes of
the same pictures are never bit-identical: a caption drawn elsewhere changes the encoder's
decisions, and on the real-Immich runs one pixel of one frame came out 27 grey levels
apart in a band with no caption in it. The probe read that pixel as a date. A caption's
letters change hundreds of pixels in strokes; the probe now counts a pixel only when a
neighbour differs too.
"""

from __future__ import annotations

from tests.integration.features.film_probe import differing_columns

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
