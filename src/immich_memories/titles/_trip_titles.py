"""Trip title text generation for map overview frames.

Produces titles like "TWO WEEKS IN LANZAROTE, SPAIN, SUMMER 2025".
Duration-aware and season-aware.
"""

from __future__ import annotations

from datetime import date

from immich_memories.i18n import film_text, film_text_n, month_name_forms, resolve_film_locale
from immich_memories.i18n_places import comma, localise_trip_place
from immich_memories.place_phrases import Place, place_phrase
from immich_memories.place_phrases.place import infer_place_kind
from immich_memories.titles.letter_case import display_upper


def _get_season(d: date) -> str:
    """Get the season name for a date (Northern Hemisphere)."""
    month = d.month
    if month in (3, 4, 5):
        return "SPRING"
    if month in (6, 7, 8):
        return "SUMMER"
    if month in (9, 10, 11):
        return "AUTUMN"
    return "WINTER"


_DURATION_KEYS = {1: "day", 2: "weekend", 3: "weekend", 7: "week", 14: "two_weeks"}
_DURATION_KEYS |= {15: "two_weeks", 21: "three_weeks"}


def _cased(text: str, capitals: bool) -> str:
    return display_upper(text) if capitals else text


def _get_duration_label(days: int, locale: str = "en", *, capitals: bool = True) -> str:
    """Convert trip duration to human-readable label ("A WEEK", "DEUX SEMAINES")."""
    key = "month" if days >= 28 else _DURATION_KEYS.get(days)
    label = film_text(f"trip.{key}", locale) if key else film_text_n("trip.days", days, locale)
    return _cased(label, capitals)


def _get_time_label(
    start_date: date, end_date: date, locale: str = "en", *, capitals: bool = True
) -> str:
    """Get the time period label (season or month name + year).

    Single month → month name ("DECEMBER 2024").
    Cross-month → season name ("SUMMER 2025").
    """
    if start_date.month == end_date.month and start_date.year == end_date.year:
        forms = month_name_forms(start_date.month, locale)
        return _cased(
            film_text("title.month_year", locale, year=start_date.year, **forms), capitals
        )
    season = film_text(f"season.{_get_season(start_date).lower()}", locale)
    if start_date.year == end_date.year:
        return _cased(
            film_text("title.season_year", locale, season=season, year=start_date.year), capitals
        )
    return _cased(
        film_text(
            "title.season_year_span",
            locale,
            season=season,
            start_year=start_date.year,
            end_year=end_date.year,
            end_year_short=f"{end_date.year % 100:02d}",
        ),
        capitals,
    )


def _localised(place: Place, locale: str) -> str:
    return localise_trip_place(place.english, place.kind, locale)


def generate_trip_title(
    location_name: str,
    start_date: date,
    end_date: date,
    locale: str = "en",
    kind: str | None = None,
    *,
    capitals: bool = True,
) -> str:
    """Generate a trip title string for a map overview frame.

    `kind` is the scale trip naming chose ("city", "island", "region",
    "regions", "country", "countries"); a label from before it was recorded
    has it inferred. The phrase comes from the language's own rules
    (`place_phrases`); a language or a place with none gets a title with no
    preposition, place first, so a wrong one never reaches the screen.

    The title card sets it in capitals; `capitals=False` gives the same words in
    ordinary case, as a description reads them ("Two weeks in Crete, Greece, Summer 2025").

    Examples:
        "TWO WEEKS IN THE NETHERLANDS, SUMMER 2025"
        "DEUX SEMAINES EN CRÈTE, GRÈCE, ÉTÉ 2025"
        "CRÈTE, GRÈCE · DEUX SEMAINES, ÉTÉ 2025" (no phrase for it)
    """
    locale = resolve_film_locale(locale)
    days = (end_date - start_date).days + 1
    duration = _get_duration_label(days, locale, capitals=capitals)
    time_label = _get_time_label(start_date, end_date, locale, capitals=capitals)
    place = Place(location_name, kind or infer_place_kind(location_name))
    phrase = place_phrase(locale, place)
    if phrase is None:
        named = _cased(_localised(place, locale), capitals)
        return f"{named} · {duration}{comma(locale)}{time_label}"
    return f"{duration} {_cased(phrase, capitals)}, {time_label}"
