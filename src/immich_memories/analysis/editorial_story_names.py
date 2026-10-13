"""What a story is called and what it shows, from its facts (no model, #2486).

A story's title used to be every episode title joined with " / ": a trip became forty-five
"posing at <town>" segments and a week at home a list of activity labels. A person names a
story by the one thing it is, so the rules do too, in this order:

- an occasion names itself ("Kit's birthday", "Pat and Lou's visit", `editorial_occasions`);
- a trip is the album the owner made for it, else the farthest place it reached
  ("Trip to Nordkapp"); each leg of it runs from its first place to its last
  ("Copenhagen to Nordkapp");
- a day is its date, at its place when it has one ("Tervuren, Sunday 6 July"); a day out
  that is no trip by the install's own rule is named the same way;
- days at home are their span ("Days at home, 1–4 July").

Every name is in the film's language (`locale`, already resolved): the wording comes from
its film-text catalogue (`story.*`), month and weekday names from CLDR. A French film was
once summarised in English story names joined by a French "puis".

Activity-classifier labels ("posing", "sport-active") never reach a name: they describe a
frame, not a happening, and are often wrong about it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from babel import Locale
from babel.dates import format_date, format_skeleton, get_day_names

from immich_memories.i18n import (
    babel_locale,
    elide_french,
    film_text,
    film_text_n,
    month_name_forms,
)

# Babel's own English is American ("July 6"); the English film text writes the day first.
_ENGLISH_DATES = "en_GB"


def story_text(key: str, locale: str, **values: object) -> str:
    """A story-name template of the film's language, filled ("Anniversaire d'Anne")."""
    text = film_text(key, locale, **values)
    return elide_french(text) if locale == "fr" else text


def story_text_n(key: str, n: int, locale: str, **values: object) -> str:
    """A plural story-name template, its form chosen by `n` the way the language counts."""
    text = film_text_n(key, n, locale, **values)
    return elide_french(text) if locale == "fr" else text


def _cldr(locale: str) -> Locale:
    return babel_locale(_ENGLISH_DATES if locale == "en" else locale)


def _day_of_month(when: date, locale: str, *, year: bool = False) -> str:
    """ "6 July", "6 juillet", "6. Juli", "7月6日": the day and its month, written in full;
    with its year ("6 July 2025") for a film over several years."""
    if year:
        return format_date(when, "long", locale=_cldr(locale))
    return format_skeleton("MMMMd", when, locale=_cldr(locale))


def _capital(text: str) -> str:
    return text[:1].upper() + text[1:]


def day_label(day: str, locale: str, *, year: bool = False) -> str:
    """ "2025-07-06" -> "Sunday 6 July", "dimanche 6 juillet", "Sonntag, 6. Juli".

    `year` writes the year too, for a film over several years: a holiday's "Monday 15
    August" and "Saturday 15 August" were otherwise two days of no particular year.
    """
    when = date.fromisoformat(day)
    weekday = get_day_names("wide", "format", _cldr(locale))[when.weekday()]
    return story_text(
        "story.weekday_date", locale, weekday=weekday, date=_day_of_month(when, locale, year=year)
    )


def span_label(first: str, last: str, locale: str, *, year: bool = False) -> str:
    """The days a story spans, as a person writes them: "1–4 July", "30 June – 2 July".

    A span across years, or any span of a film over several years (`year`), writes its
    dates whole: "15 August 2004 – 15 August 2022", never "15 August – 15 August".
    """
    start, end = date.fromisoformat(first), date.fromisoformat(last)
    if start == end:
        return _day_of_month(start, locale, year=year)
    if year or start.year != end.year:
        return story_text(
            "story.span",
            locale,
            first=_day_of_month(start, locale, year=True),
            last=_day_of_month(end, locale, year=True),
        )
    if start.month == end.month:
        month = month_name_forms(end.month, locale)["month_of"]
        return story_text(
            "story.span_same_month", locale, start=start.day, end=end.day, month=month
        )
    return story_text(
        "story.span", locale, first=_day_of_month(start, locale), last=_day_of_month(end, locale)
    )


def _at(place: str, when: str, locale: str) -> str:
    return story_text("story.place_when", locale, place=place, when=when)


def home_name(
    days: Sequence[str], places: Sequence[str], locale: str, *, year: bool = False
) -> tuple[str, str]:
    """A story at home that is no occasion: its day, or its span of days."""
    first, last = min(days), max(days)
    if first == last:
        day = day_label(first, locale, year=year)
        name = _at(places[0], day, locale) if len(set(places)) == 1 else _capital(day)
        return name, story_text("story.home_day_purpose", locale, day=day)
    span = span_label(first, last, locale, year=year)
    name = story_text("story.home_days", locale, span=span)
    return name, _across(places, story_text("story.home_days_purpose", locale), locale)


def outing_name(
    days: Sequence[str], places: Sequence[str], locale: str, *, year: bool = False
) -> tuple[str, str]:
    """A stay away too near or too short to be a trip: where it went, and when."""
    first, last = min(days), max(days)
    named = list(dict.fromkeys(p for p in places if p))
    when = (
        day_label(first, locale, year=year)
        if first == last
        else span_label(first, last, locale, year=year)
    )
    name = _at(named[-1], when, locale) if named else _capital(when)
    head = story_text("story.day_out" if first == last else "story.days_out", locale)
    if named:
        return name, _across(places, head, locale)
    return name, story_text("story.head_when", locale, head=head, when=when)


def trip_name(*, album: str | None, farthest: str | None, locale: str) -> str:
    """The trip as a whole: the owner's album for it, else where it reached."""
    if album:
        return album
    if farthest:
        return story_text("story.trip_to", locale, place=farthest)
    return story_text("story.trip_away", locale)


def leg_name(places: Sequence[str], *, trip: str, legs: int, locale: str) -> str:
    """One leg of a trip, from its first place to its last; a one-leg trip is the trip."""
    named = [p for p in places if p]
    if legs <= 1 or not named:
        return trip
    first, last = named[0], named[-1]
    return first if first == last else story_text("story.leg", locale, first=first, last=last)


def trip_purpose(days: Sequence[str], places: Sequence[str], locale: str) -> str:
    """ "19 days away, Copenhagen to Kristiansand"-style facts."""
    first, last = min(days), max(days)
    count = (date.fromisoformat(last) - date.fromisoformat(first)).days + 1
    named = list(dict.fromkeys(p for p in places if p))
    head = story_text_n("story.days_away", count, locale)
    if len(named) >= 2:
        return story_text("story.from_to", locale, head=head, first=named[0], last=named[-1])
    return story_text("story.in_place", locale, head=head, place=named[0]) if named else head


def _across(places: Sequence[str], head: str, locale: str) -> str:
    named = list(dict.fromkeys(p for p in places if p))
    if not named:
        return head
    shown = ", ".join(named[:3])
    if len(named) > 3:
        shown = story_text_n("story.more_places", len(named) - 3, locale, places=shown)
    return story_text("story.across", locale, head=head, places=shown)
