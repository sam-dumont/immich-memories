"""Guards that refuse a model title for what it invents, drops or mislays.

A model answers the title prompt in `llm_titles.py`; what it writes may name
something no fact names, drop the year the template title would show, or
(for a trip) leave out the place it must name. Each guard here takes the raw
suggestion and returns it, a trimmed version, or ``None`` to fall back to the
template.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import date
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Literal

logger = logging.getLogger(__name__)

TripType = Literal["multi_base", "base_camp", "road_trip", "hiking_trail"]
MapMode = Literal["title_only", "excursions", "overnight_stops"]

# Which prompt a memory gets. A film about people is named from the family
# record; an occasion from what the occasion was. Everything else is a trip.
PEOPLE_MEMORY_TYPES = frozenset({"person_spotlight", "multi_person"})
OCCASION_MEMORY_TYPES = frozenset(
    {
        "album",
        "holiday",
        "monthly_highlights",
        "on_this_day",
        "season",
        "special_day",
        "year",
        "year_in_review",
    }
)


def _is_trip(memory_type: str) -> bool:
    """Whether this memory is named by the trip prompt, which also classifies the route."""
    return memory_type not in PEOPLE_MEMORY_TYPES and memory_type not in OCCASION_MEMORY_TYPES


@dataclass
class TitleSuggestion:
    """LLM-generated title and trip classification."""

    title: str
    subtitle: str | None = None
    trip_type: TripType | None = None
    map_mode: MapMode | None = None


# Languages spell the same place their own way (Brussels/Bruxelles,
# Gent/Ghent), so a name the facts carry and a name the title writes are the
# same name when they are this close, and different names below it.
_SAME_NAME_RATIO = 0.6


def _name_words(text: str) -> list[str]:
    """Letter-only words, accents folded away so Genève matches Geneve."""
    flattened = "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )
    return re.findall(r"[^\W\d_]+", flattened)


def _is_a_known_name(word: str, known: set[str]) -> bool:
    lowered = word.casefold()
    return any(SequenceMatcher(None, lowered, name).ratio() >= _SAME_NAME_RATIO for name in known)


@lru_cache(maxsize=1)
def _calendar_words() -> frozenset[str]:
    """Month and weekday names in every film language: a date spelled out, never a name.

    The facts carry dates as numbers, so without this "Porto in January" reads as a
    title that names something no fact names. Wide names only: an abbreviation such
    as "Jan" is also a first name.
    """
    from babel.dates import get_day_names, get_month_names

    from immich_memories.i18n import SUPPORTED_LOCALES, babel_locale

    words: set[str] = set()
    for code in SUPPORTED_LOCALES:
        where = babel_locale(code)
        for context in ("format", "stand-alone"):
            for names in (
                get_month_names("wide", context, where),
                get_day_names("wide", context, where),
            ):
                for name in names.values():
                    words.update(word.casefold() for word in _name_words(name))
    return frozenset(words)


@lru_cache(maxsize=1)
def _one_word_places() -> dict[str, frozenset[str]]:
    """Countries, islands and regions named in one word, in every film language.

    Folded word -> the places it names (a CLDR code or an English area name),
    so "Chypre", "Cyprus" and "Кипр" are one place and "Chypre" is not "type".
    """
    from immich_memories.i18n import SUPPORTED_LOCALES, babel_locale
    from immich_memories.place_names import area_name_groups

    groups: dict[str, set[str]] = {k: set(v) for k, v in area_name_groups().items()}
    for code in SUPPORTED_LOCALES:
        for territory, name in babel_locale(code).territories.items():
            if territory.isalpha():  # "150" is Europe, "001" the world: not a place visited
                groups.setdefault(territory, set()).add(name)
    places: dict[str, set[str]] = {}
    for key, names in groups.items():
        for name in names:
            if len(words := _name_words(name)) == 1:
                places.setdefault(words[0].casefold(), set()).add(key)
    return {word: frozenset(keys) for word, keys in places.items()}


def _names_a_fact(word: str, known: set[str]) -> bool:
    """Whether `word` is a name the facts carry: the same place, or close in spelling."""
    places = _one_word_places().get(word.casefold())
    if places is None:
        return _is_a_known_name(word, known)
    return any(places & _one_word_places().get(name, frozenset()) for name in known)


def invented_name(line: str, facts: str) -> str | None:
    """The first name this line uses that the facts do not, if it uses one.

    A capitalised word past the first is a proper noun in the languages the
    title screens speak. The first word is capitalised by orthography alone, so
    it counts only when it is a country, island or region's whole name. A place
    passes only when the facts name that same place, in any language. So this
    catches an invented name, not invention: a reworded fact passes, a festival
    or a country nobody recorded does not.
    """
    known = {word.casefold() for word in _name_words(facts)}
    words = _name_words(line)
    named = [word for word in words[1:] if word[:1].isupper()]
    if words and words[0].casefold() in _one_word_places():
        named.insert(0, words[0])
    return next(
        (
            word
            for word in named
            if word.casefold() not in _calendar_words() and not _names_a_fact(word, known)
        ),
        None,
    )


def restore_fact_casing(suggestion: TitleSuggestion, facts: str) -> TitleSuggestion:
    """A name the facts spell with a capital keeps it, whatever case the model wrote it in.

    Asked for sentence case, a small model lowercases proper nouns too ("Mai à split"). Only a
    word of three letters or more that the facts themselves capitalise is touched.
    """
    names = {word.casefold() for word in _name_words(facts) if word[:1].isupper() and len(word) > 2}

    def capital(match: re.Match[str]) -> str:
        word = match.group(0)
        flat = _name_words(word)
        if word[:1].islower() and flat and flat[0].casefold() in names:
            return word[:1].upper() + word[1:]
        return word

    def fixed(text: str | None) -> str | None:
        return re.sub(r"[^\W\d_]+", capital, text) if text else text

    return replace(
        suggestion,
        title=fixed(suggestion.title) or suggestion.title,
        subtitle=fixed(suggestion.subtitle),
    )


def _refusing_invented_names(
    suggestion: TitleSuggestion | None, facts: str
) -> TitleSuggestion | None:
    """The suggestion, minus whatever part of it names something unrecorded."""
    if suggestion is None or not facts:
        return suggestion
    if invented := invented_name(suggestion.title, facts):
        logger.warning(
            "Title names %r, which no fact names; the template names this memory instead", invented
        )
        return None
    if suggestion.subtitle and (invented := invented_name(suggestion.subtitle, facts)):
        logger.info("Subtitle names %r, which no fact names; dropping the subtitle", invented)
        return replace(suggestion, subtitle=None)
    return suggestion


def names_the_place(title: str, place: str, locale: str) -> bool:
    """Whether `title` names the trip's place, in English or in `locale`.

    Any of the place's own words counts ("Crete" or "Crète" for "Crete,
    Greece", "Utah" for "Utah and Nevada, United States"), spelled as close as
    `_SAME_NAME_RATIO` allows.
    """
    from immich_memories.i18n_places import localise_place

    spellings = f"{place} {localise_place(place, locale) or ''}".replace(" and ", " ")
    known = {word.casefold() for word in _name_words(spellings) if len(word) > 2}
    if not known:
        return True
    # WHY exact under four letters: "été" is as close to "Crete" as "Crète" is.
    return any(
        w.casefold() in known or (len(w) > 3 and _is_a_known_name(w, known))
        for w in _name_words(title)
    )


def _requiring_the_place(
    suggestion: TitleSuggestion | None, place: str | None, locale: str
) -> TitleSuggestion | None:
    if suggestion is None or not place or names_the_place(suggestion.title, place, locale):
        return suggestion
    logger.warning(
        "Title %r does not name the trip's place %r; the template names this trip instead",
        suggestion.title,
        place,
    )
    return None


# A person spotlight spanning several years opens on the name alone; "on this
# day" is never dated; a birthday is an ordinal, never a calendar year. These
# are the only shapes `generate_title`'s own dispatch can return with no year
# in them, so `_template_names_no_year` checks against exactly this set.
_SELECTION_TYPES_WITH_NO_YEAR = frozenset({"on_this_day", "person_spotlight", "birthday_year"})


def _template_names_no_year(
    memory_type: str, start: date, end: date, person_names: tuple[str, ...]
) -> bool:
    """Whether the BASIC template's own dispatch names this memory with no year.

    Walks the same path the renderer uses (`infer_selection_type` then
    `generate_title`) and reads back the shape it actually resolved to — not
    the one first guessed, since a nameless person spotlight or a yearless
    span reroutes itself to a dated shape inside `generate_title` itself.
    """
    from immich_memories.titles.text_builder import generate_title, infer_selection_type

    selection_type = infer_selection_type(start_date=start, end_date=end, memory_type=memory_type)
    person_name = person_names[0] if memory_type == "person_spotlight" and person_names else None
    info = generate_title(
        selection_type, start_date=start, end_date=end, person_name=person_name, locale="en"
    )
    return info.selection_type.value in _SELECTION_TYPES_WITH_NO_YEAR


def _required_years(
    memory_type: str,
    start: date,
    end: date,
    person_names: tuple[str, ...],
    holiday: str | None,
) -> frozenset[int]:
    """The year(s) the BASIC template's own title would show for this memory.

    A trip's map title always carries its year(s). A holiday's title is its
    name, read off `holiday_label`, which never carries one. Everything else
    walks the same dispatch the renderer uses so the model is held to exactly
    what the fallback would show, no more and no less.
    """
    if not _is_trip(memory_type) and (
        holiday or _template_names_no_year(memory_type, start, end, person_names)
    ):
        return frozenset()
    years = {start.year}
    if end.year != start.year:
        years.add(end.year)
    return frozenset(years)


def _years_named(text: str, required: frozenset[int]) -> bool:
    """Whether every required year's four digits (or a cross-year short form) is in `text`."""
    years = sorted(required)
    if not years:
        return True
    first, *rest = years
    if str(first) not in text:
        return False
    for year in rest:
        if str(year) in text:
            continue
        short = f"{year % 100:02d}"
        if not re.search(rf"{first}[\s–—\-/]{{0,3}}{short}\b", text):
            return False
    return True


def _requiring_the_year(
    suggestion: TitleSuggestion | None,
    memory_type: str,
    start_date: str,
    end_date: str,
    person_names: tuple[str, ...],
    holiday: str | None,
) -> TitleSuggestion | None:
    """The suggestion, unless it drops a year the template title would show.

    The template shows no year for a holiday, "on this day", or a person
    spotlight spanning several years (it opens on the name alone); every
    other span must carry its year, in the title or the subtitle, or the
    template names this memory instead.
    """
    if suggestion is None:
        return suggestion
    start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    required = _required_years(memory_type, start, end, person_names, holiday)
    if not required:
        return suggestion
    combined = f"{suggestion.title} {suggestion.subtitle or ''}"
    if _years_named(combined, required):
        return suggestion
    logger.warning(
        "Title %r (subtitle %r) does not name the required year(s) %s for %s to %s; "
        "the template names this memory instead",
        suggestion.title,
        suggestion.subtitle,
        sorted(required),
        start_date,
        end_date,
    )
    return None
