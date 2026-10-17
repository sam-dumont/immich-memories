"""The per-clip date caption: what it says and how it is drawn.

Kept apart from the assembler because none of it depends on decoding — it is
text and geometry, and it is worth testing without spinning up FFmpeg.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from babel import Locale
from babel.dates import format_date, format_skeleton

from immich_memories.i18n import babel_locale
from immich_memories.processing.caption_image import (
    CaptionStyle,
    needs_image,
    render_caption,
    text_width,
)
from immich_memories.titles.letter_case import display_upper
from immich_memories.titles.text_layout import shrink_to_width

# Caption metrics as a share of the frame's short side, so the date reads the
# same on a 4K memory and a 720p one. Captions provide quiet context;
# title cards carry the large typography.
_FONT_RATIO = 0.0444
_MARGIN_RATIO = 0.055
# How far a long place caption may shrink before it is shortened instead: below
# this share of the caption size it stops reading as the date's companion line.
_MIN_PLACE_SCALE = 0.6

# 0xBF is 75% of full range: HLG graphics white. Measured, plain white@0.85
# draws at 872/1023 in a 10-bit pipe, which glares above the picture's own
# diffuse white; this lands at 721.
_HDR_COLOUR = "0xBFBFBF"
_SDR_COLOUR = "white"
_HDR_RGB = (0xBF, 0xBF, 0xBF)
_SDR_RGB = (0xFF, 0xFF, 0xFF)


@dataclass(frozen=True)
class ClipCaption:
    """What one clip shows: a place (left) and a date (right), either empty."""

    place: str = ""
    date: str = ""

    def __bool__(self) -> bool:
        return bool(self.place or self.date)


def captions_for_timeline(
    clips: list[Any], *, place: bool = False, locale_code: str = "en"
) -> list[ClipCaption]:
    """Captions for a clip sequence, with dates and places independently deduplicated.

    The interesting information in a place caption is the CHANGE of place, so
    it appears when it differs from the last known place and stays silent while
    the location holds. A clip without EXIF place does not reset the run —
    gaps are common inside one event, and repeating "Nice, France" after every
    gap would caption almost every clip.
    """
    dates = [_parsed_date(clip) for clip in clips]
    known = [d for d in dates if d is not None]
    # The span of the CONTENT is the period the viewer already knows: a video
    # of one August needs no "Aug 2025" on every clip, only the day.
    same_month = bool(known) and len({(d.year, d.month) for d in known}) == 1
    same_year = bool(known) and len({d.year for d in known}) == 1

    captions: list[ClipCaption] = []
    last_place: str | None = None
    last_date: date | None = None
    for clip, taken in zip(clips, dates, strict=True):
        shown_place = ""
        if place:
            where = getattr(clip, "caption_location_name", None)
            if where is None:
                where = getattr(clip, "location_name", None)
            # Display text can lose its country after the first caption. Compare the
            # original place identity so "Nice, France" -> "Nice" is not a city change.
            identity = getattr(clip, "location_name", None) or where
            if where is not None and identity != last_place:
                shown_place = str(where)
                last_place = identity
        captions.append(
            ClipCaption(
                place=shown_place,
                date=_worded(taken, same_month, same_year, locale_code)
                if taken != last_date
                else "",
            )
        )
        if taken is not None:
            last_date = taken
    return captions


# Scripts that write a date without spaces, weekday after the day ("14日木曜日").
_CJK = frozenset({"ja", "zh-Hans", "ko"})


def _date_locale(locale_code: str) -> Locale:
    # WHY en_GB: Babel's "en" is American ("August 10"); the captions have
    # always said "10 August", and a changed English caption was not asked for.
    return Locale.parse("en_GB") if locale_code == "en" else babel_locale(locale_code)


def _worded(taken: date | None, same_month: bool, same_year: bool, locale_code: str) -> str:
    """The date the way the film's language writes it (CLDR), from the day up to what is new."""
    if taken is None:
        return ""
    where = _date_locale(locale_code)
    if same_month:
        if locale_code in _CJK:
            return _plain_spaces(format_skeleton("EEEEd", taken, locale=where))
        return _weekday_and_day(taken, where)
    if same_year:
        return _plain_spaces(format_skeleton("MMMMd", taken, locale=where))
    return _plain_spaces(format_date(taken, format="long", locale=where))


def _weekday_and_day(taken: date, where: Locale) -> str:
    """ "Sunday 10", "Sonntag, 10.": CLDR's order for the two, with the weekday written out."""
    pattern = where.datetime_skeletons["Ed"].pattern
    # CLDR's pattern abbreviates the weekday ("So., 10."); the caption has always written it out.
    pattern = re.sub(r"E+", "EEEE", re.sub(r"c+", "cccc", pattern))
    worded = _plain_spaces(format_date(taken, format=pattern, locale=where))
    return worded[:1].upper() + worded[1:]


def _plain_spaces(text: str) -> str:
    # WHY: CLDR puts no-break spaces in dates ("2025\u202fг."); the caption
    # face has no glyph for them, and a caption never wraps anyway.
    return text.replace("\u202f", " ").replace("\xa0", " ")


def _parsed_date(clip: Any) -> date | None:
    raw = getattr(clip, "date", None)
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _escape(text: str) -> str:
    """Escape for drawtext, which parses its own options out of the value.

    A raw colon does not merely look wrong, it fails the filter graph. Backslash
    goes first, or it would double-escape everything added after it.

    The apostrophe is substituted rather than escaped. Measured against a
    `textfile=` reference render, drawtext silently *drops* an ASCII apostrophe
    however it is escaped -- \\', \\\\', quoted or not, all render "LAquila"
    for "L'Aquila" -- so the only forms that reach the screen are a temp file per
    caption or U+2019, which is the correct typographic mark regardless.
    """
    stripped = "".join(c for c in text if c == " " or (ord(c) >= 32 and ord(c) != 127))
    for old, new in (
        ("\\", "\\\\"),
        (":", "\\:"),
        # Measured: drawtext drops an ASCII apostrophe however it is escaped.
        ("'", "’"),
        ("%", "\\%"),
        ("[", "\\["),
        ("]", "\\]"),
        (";", "\\;"),
    ):
        stripped = stripped.replace(old, new)
    return stripped


def _filter_path(path: object) -> str:
    """A file path as a filter option value inside a filter graph.

    WHY (#2348): FFmpeg unescapes the graph first, then the filter's options, so
    one level of quoting is spent before the option parser sees the value. A ':'
    (a Windows drive) or an apostrophe (a home folder) then broke every caption.
    Escape once for the options, then once more for the graph.
    """
    option = "".join("\\" + c if c in "\\':" else c for c in str(path))
    return "".join("\\" + c if c in "\\'[],;" else c for c in option)


def _overlay(label: str, text: str, style: CaptionStyle, x: int, y: int, window: str) -> str:
    """An `overlay` of the caption's image, as a piece of the decoder's filter chain.

    The chain is joined with commas, so this closes it into a labelled pad,
    opens the image as a second input, and hands the overlaid result on to
    whatever filter comes next.

    The image is converted to limited range before it meets the frame. Left
    to itself, FFmpeg 8.1 negotiates the overlay in full range (the PNG's)
    and stretches the whole untagged frame to match, which the rawvideo pipe
    then reads as limited: the video under the caption brightens.
    """
    path, dx, dy = render_caption(text, style)
    return (
        f"null[{label}_frame];movie={_filter_path(path)},scale=out_range=tv,setparams=range=tv[{label}_text];"
        f"[{label}_frame][{label}_text]overlay=x={x + dx}:y={y + dy}{window}"
    )


def caption_filters(
    caption: ClipCaption,
    width: int,
    height: int,
    *,
    is_hdr: bool = False,
    font_path: str | None = None,
    frame_window: tuple[int, int] | None = None,
) -> list[str]:
    """FFmpeg drawtext filters: the place top-left, the date bottom-right.

    Small translucent uppercase, anchored at constant y in both orientations.
    A light outline preserves readability without making every clip a title.
    """
    short_side = min(width, height)
    font_size = max(12, round(short_side * _FONT_RATIO))
    inset = round(short_side * _MARGIN_RATIO)
    line = round(font_size * 1.05)
    window = ""
    if frame_window is not None:
        start, end = frame_window
        window = f":enable='gte(n,{start})*lt(n,{end})'"
    filters = []
    place = display_upper(caption.place)
    place_size = font_size
    if font_path and place and Path(font_path).is_file():
        place, place_size = _fitted_place(place, font_path, font_size, width - 2 * inset)
    if font_path and needs_image(place, font_path):
        style = _style(font_path, place_size, is_hdr)
        filters.append(_overlay("place", place, style, inset, inset, window))
    elif place:
        drawn = _drawtext_options(place_size, is_hdr, font_path) + window
        filters.append(f"drawtext=text='{_escape(place)}'{drawn}:x={inset}:y={inset}")
    day = display_upper(caption.date)
    if font_path and needs_image(day, font_path):
        style = _style(font_path, font_size, is_hdr)
        x = width - text_width(day, style) - inset
        filters.append(_overlay("date", day, style, x, height - inset - line, window))
    elif day:
        drawn = _drawtext_options(font_size, is_hdr, font_path) + window
        filters.append(f"drawtext=text='{_escape(day)}'{drawn}:x=w-tw-{inset}:y=h-{inset}-{line}")
    return filters


def _style(font_path: str, font_size: int, is_hdr: bool) -> CaptionStyle:
    return CaptionStyle(
        font_path,
        font_size,
        _HDR_RGB if is_hdr else _SDR_RGB,
        max(1, font_size // 24),
        max(1, font_size // 32),
    )


def _drawtext_options(font_size: int, is_hdr: bool, font_path: str | None) -> str:
    """drawtext's look at this size: the same colour, outline and shadow `_style` draws."""
    options = (
        f":fontsize={font_size}"
        f":fontcolor={_HDR_COLOUR if is_hdr else _SDR_COLOUR}@0.85"
        f":borderw={max(1, font_size // 24)}:bordercolor=black@0.45"
        ":shadowcolor=black@0.35"
        f":shadowx={max(1, font_size // 32)}:shadowy={max(1, font_size // 32)}"
    )
    return f":fontfile={_filter_path(font_path)}{options}" if font_path else options


def _fitted_place(place: str, font_path: str, font_size: int, max_width: int) -> tuple[str, int]:
    """The place caption and the size it fits the frame at: smaller first, shorter last (#2637).

    The same rule as the map pins' labels (`fit_pin_label_font`): a long name shrinks
    so it never runs off a portrait frame, down to a size that still reads beside the
    date; only a name too long even there loses its end to an ellipsis.
    """
    min_size = max(12, round(font_size * _MIN_PLACE_SCALE))
    size = shrink_to_width(
        lambda at: text_width(place, _style(font_path, at, is_hdr=False)),
        font_size,
        max_width,
        min_size,
    )
    fitted = _style(font_path, size, is_hdr=False)
    if text_width(place, fitted) <= max_width:
        return place, size
    shortened = place
    while shortened and text_width(f"{shortened}…", fitted) > max_width:
        shortened = shortened[:-1].rstrip(" ,")
    return f"{shortened}…", size


def caption_font_path() -> str | None:
    """The captions' font file: Outfit SemiBold, the flagship title family.

    One face for every caption rather than chasing the run's title style —
    consistent product typography, and the bundled file needs no network.
    None falls back to drawtext's default rather than failing the render.
    """
    from immich_memories.titles.fonts import get_font_path

    path = get_font_path("Outfit", "SemiBold")
    return str(path) if path else None


def caption_frame_windows(
    clips: list, transitions: list[str], fps: int, fade_frames: int
) -> list[tuple[int, int] | None]:
    """Keep burnt-in captions out of both sides of each dissolve.

    A clip too short to hold a body between its fades gets no window at all.
    The alternative is a window FFmpeg can never satisfy, which drops that
    clip's caption silently.
    """
    windows: list[tuple[int, int] | None] = []
    for clip, incoming, outgoing in zip(
        clips, ["cut", *transitions], [*transitions, "cut"], strict=True
    ):
        start = fade_frames if incoming == "fade" else 0
        end = int(clip.duration * fps) - (fade_frames if outgoing == "fade" else 0)
        windows.append((start, end) if start < end else None)
    return windows


def timeline_captions(
    clips: list,
    date_overlay: bool,
    place_overlay: bool,
    locale_code: str = "en",
) -> tuple[list[ClipCaption] | None, str | None]:
    """Captions for the whole sequence, or nothing when neither flag is set.

    Timeline-aware (independent dedupe, span-relative dates), so computed once for
    the sequence rather than per decoder.
    """
    if not (date_overlay or place_overlay):
        return None, None
    captions = captions_for_timeline(clips, place=place_overlay, locale_code=locale_code)
    if not date_overlay:
        captions = [ClipCaption(place=c.place) for c in captions]
    return captions, caption_font_path()
