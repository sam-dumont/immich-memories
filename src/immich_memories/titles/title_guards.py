"""Guards that refuse a model title for what it invents, drops or mislays.

A model answers the title prompt in `llm_titles.py`; what it writes may name
something no fact names, drop a year the template title would show, or (for
a trip) leave out the place it must name. Each guard here takes the raw
suggestion and returns it, a trimmed version, or ``None`` to fall back to the
template. `required_years` is also called before the model is asked, so its
answer can be put in the prompt as a fact rather than left to prompt wording
that could drift from what this guard actually checks.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from difflib import SequenceMatcher
from functools import lru_cache
from typing import TYPE_CHECKING

from immich_memories.titles.relationship_words import (
    FAMILY_GENERIC,
    FAMILY_TYPES,
    relationship_words,
)
from immich_memories.titles.title_routing import is_trip
from immich_memories.titles.title_suggestion import TitleSuggestion

if TYPE_CHECKING:
    from immich_memories.db import Store
    from immich_memories.people.context import PersonPromptContext

logger = logging.getLogger(__name__)

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


def refusing_invented_names(
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


def requiring_the_place(
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


# Digits only, in any of the 14 film locales (ja/ko/zh carry a trailing script
# character, e.g. "2026年", which this boundary ignores since it isn't a digit).
_YEAR_DIGITS = re.compile(r"(?<!\d)\d{4}(?!\d)")

# The separators a cross-year title can put between a full start year and the
# end year's two-digit short form: a hyphen/en-dash/em-dash/slash/space in
# Western locales, a wave dash or fullwidth tilde in ja/ko/zh ("2024〜25年").
_YEAR_RANGE_SEP = "\\s\u2013\u2014\u301c\uff5e~/-"


def required_years(
    memory_type: str,
    start: date,
    end: date,
    person_names: tuple[str, ...],
    holiday: str | None,
) -> frozenset[int]:
    """The year(s) the BASIC template's own title would show for this memory.

    A trip's map title always carries its year(s). A holiday's title is its
    name, read off `holiday_label`, which never carries one. Everything else
    walks the same dispatch the renderer uses (`infer_selection_type` then
    `generate_title`) and reads the years back out of what it actually wrote —
    not a list of which selection types are "supposed" to carry one, since a
    nameless person spotlight or a yearless span reroutes itself to a dated
    shape inside `generate_title` itself.

    French is read, not the film's own locale: every locale's catalogue spells
    a lone year in full, but English abbreviates a cross-year season's end
    year ("Summer 2024–25"), which would under-read a two-year span here.
    """
    if is_trip(memory_type):
        years = {start.year}
        if end.year != start.year:
            years.add(end.year)
        return frozenset(years)
    if memory_type == "holiday" and holiday:
        return frozenset()
    from immich_memories.titles.text_builder import generate_title, infer_selection_type

    selection_type = infer_selection_type(start_date=start, end_date=end, memory_type=memory_type)
    person_name = person_names[0] if memory_type == "person_spotlight" and person_names else None
    info = generate_title(
        selection_type, start_date=start, end_date=end, person_name=person_name, locale="fr"
    )
    combined = f"{info.main_title} {info.subtitle or ''}"
    return frozenset(int(y) for y in _YEAR_DIGITS.findall(combined))


def _years_named(text: str, required: frozenset[int]) -> bool:
    """Whether every required year's four digits (or a cross-year short form) is in `text`."""
    years = sorted(required)
    if not years:
        return True
    first, *rest = years
    if not re.search(rf"(?<!\d){first}(?!\d)", text):
        return False
    for year in rest:
        if re.search(rf"(?<!\d){year}(?!\d)", text):
            continue
        short = f"{year % 100:02d}"
        if not re.search(rf"(?<!\d){first}[{_YEAR_RANGE_SEP}]{{0,3}}{short}(?!\d)", text):
            return False
    return True


def requiring_the_year(
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
    required = required_years(memory_type, start, end, person_names, holiday)
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


def _title_states_a_single_year(title: str, required: frozenset[int]) -> bool:
    """Whether `title` alone names exactly one of several required years.

    A cross-year title is allowed to carry both years as a range ("2024-26")
    within the title itself; naming only one of them, with the other left for
    the subtitle, reads as a single-year headline on a multi-year span.
    """
    named = {int(y) for y in _YEAR_DIGITS.findall(title)}
    if len(named) != 1 or not named < required:
        return False
    return not _years_named(title, required)


def refusing_single_year_title(
    suggestion: TitleSuggestion | None,
    memory_type: str,
    start_date: str,
    end_date: str,
    person_names: tuple[str, ...],
    holiday: str | None,
) -> TitleSuggestion | None:
    """The suggestion, unless its TITLE states a single year on a multi-year span.

    `requiring_the_year` already lets a cross-year span's years split across
    title and subtitle; this catches the title claiming only one of them on
    its own ("en 2024" opening a 2024-2026 film), which misreads the span even
    when the subtitle completes it.
    """
    if suggestion is None:
        return suggestion
    start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    required = required_years(memory_type, start, end, person_names, holiday)
    if len(required) < 2 or not _title_states_a_single_year(suggestion.title, required):
        return suggestion
    logger.warning(
        "Title %r names only one of the required years %s for a span reaching several; "
        "the template names this memory instead",
        suggestion.title,
        sorted(required),
    )
    return None


def _template_title_text(
    memory_type: str,
    start: date,
    end: date,
    person_names: Sequence[str],
    locale: str,
) -> str:
    """The BASIC template's own main title for this memory, in `locale`.

    The subtitle is left out: it is usually the subject's own name, which a
    model title is free to repeat without that repeat counting as "no new
    content" -- only the headline itself sets the bar a model title must clear.
    """
    from immich_memories.titles.text_builder import generate_title, infer_selection_type

    selection_type = infer_selection_type(start_date=start, end_date=end, memory_type=memory_type)
    person_name = person_names[0] if memory_type == "person_spotlight" and person_names else None
    info = generate_title(
        selection_type, start_date=start, end_date=end, person_name=person_name, locale=locale
    )
    return info.main_title


# Words too small to carry a title's own content: articles, conjunctions and
# the handful of "year" nouns that let a bare year through as a non-answer
# ("L'année 2025"). Not a stopword list for prose -- only what a title's
# filler commonly is, across the film's locales.
_FILLER_WORDS = frozenset(
    {
        "l'année", "l'annee", "année", "annee", "le", "la", "les", "un", "une", "des", "de", "du",
        "et", "en",
        # Fragments an elided "l'/d'/qu'/..." splits off (apostrophe is not a word character).
        "l", "d", "j", "qu", "n", "s", "c",
        "the", "a", "an", "and", "of", "in", "year",
        "el", "los", "las", "y", "año", "ano",
        "der", "die", "das", "und", "im", "jahr",
        "il", "lo", "gli", "e", "anno",
        "het", "een",
        "o", "os", "as",
        "rok", "roku", "i",
        "år", "och", "ett",
    }
)  # fmt: skip


def _content_words(text: str) -> set[str]:
    """The words of `text` that are not filler: what the title actually says."""
    return {w.casefold() for w in _name_words(text) if w.casefold() not in _FILLER_WORDS}


def refusing_contentless_title(
    suggestion: TitleSuggestion | None,
    memory_type: str,
    start_date: str,
    end_date: str,
    person_names: tuple[str, ...],
    locale: str,
) -> TitleSuggestion | None:
    """The suggestion, unless it adds no content word over the template's own title.

    "L'année 2025" over the template's "2025" differs only by filler; the
    template names the same year more plainly, so it wins.
    """
    if suggestion is None:
        return suggestion
    start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    template = _template_title_text(memory_type, start, end, person_names, locale)
    if _content_words(suggestion.title) - _content_words(template):
        return suggestion
    logger.info(
        "Title %r adds no content word over the template %r; using the template instead",
        suggestion.title,
        template,
    )
    return None


def _add_person_relations(
    name: str,
    context: PersonPromptContext,
    names_in_film: set[str],
    holders: dict[str, set[str]],
) -> None:
    """Every relation type `name` holds, to the maker or to another named person."""
    from immich_memories.people.relationships import owner_role

    for kind in context.owner_relationship_kinds:
        if type_word := owner_role(kind):
            holders.setdefault(type_word.casefold(), set()).add(name)
    if context.role:
        holders.setdefault(context.role.strip().casefold(), set()).add(name)
    for rel in context.relationships:
        if rel.target_name in names_in_film:
            type_word = owner_role(rel.kind) or rel.kind.replace("-of", "").replace("-", " ")
            holders.setdefault(type_word.casefold(), set()).add(name)


def _recorded_relation_people(
    person_names: Sequence[str], people_store: Store | None
) -> dict[str, set[str]]:
    """Relation type -> which of the film's people hold it (to the maker or to each other)."""
    from immich_memories.people.context import load_people_prompt_context

    by_name = {
        entry.name: entry
        for entry in load_people_prompt_context(people_store, include_derived=True).values()
    }
    names_in_film = set(person_names)
    holders: dict[str, set[str]] = {}
    for name in person_names:
        if (context := by_name.get(name)) is not None:
            _add_person_relations(name, context, names_in_film, holders)
    return holders


# Japanese, Korean and Chinese write compound words with no space between
# them, so a word boundary never falls either side of a relationship word;
# these scripts are matched by plain substring instead.
_NO_WORD_BOUNDARY_SCRIPT = re.compile(r"[぀-ヿ㐀-鿿가-힯]")


def _contains_relationship_word(lowered: str, word: str) -> bool:
    folded = word.casefold()
    if _NO_WORD_BOUNDARY_SCRIPT.search(folded):
        return folded in lowered
    return re.search(rf"(?<![\w-]){re.escape(folded)}(?![\w-])", lowered) is not None


def _unfounded_relationship_word(
    text: str, words: dict[str, tuple[str, bool]], holders: dict[str, set[str]]
) -> str | None:
    """The first relationship word in `text` the recorded relations do not back, if any."""
    lowered = text.casefold()
    for word, (relation_type, plural) in sorted(words.items(), key=lambda kv: -len(kv[0])):
        if not _contains_relationship_word(lowered, word):
            continue
        if relation_type == FAMILY_GENERIC:
            if any(t in holders for t in FAMILY_TYPES):
                continue
            return word
        people = holders.get(relation_type, set())
        if not people or (plural and len(people) < 2):
            return word
    return None


def refusing_unfounded_relationships(
    suggestion: TitleSuggestion | None,
    person_names: Sequence[str],
    locale: str,
    people_store: Store | None,
) -> TitleSuggestion | None:
    """The suggestion, minus a relationship word the family record does not back.

    A relationship word is backed when the recorded relations between the
    film's own people (to the maker, or to each other) include that relation
    type, for at least as many people as the word's grammatical number
    claims. A friend called "le fils" of parents who are not in the film, or
    one grandchild called "les petits-enfants", falls back to the template;
    an unfounded word in the subtitle alone only drops the subtitle.
    """
    if suggestion is None:
        return suggestion
    words = relationship_words(locale)
    holders = _recorded_relation_people(person_names, people_store)
    if bad := _unfounded_relationship_word(suggestion.title, words, holders):
        logger.warning(
            "Title %r calls somebody %r, a relation the family record does not back; "
            "the template names this memory instead",
            suggestion.title,
            bad,
        )
        return None
    if suggestion.subtitle and (
        bad := _unfounded_relationship_word(suggestion.subtitle, words, holders)
    ):
        logger.info("Subtitle calls somebody %r, which the family record does not back", bad)
        return replace(suggestion, subtitle=None)
    return suggestion


_FRENCH_ELISION_VOWELS = frozenset("aàâeéèêëiîïoôuùûüyhAÀÂEÉÈÊËIÎÏOÔUÙÛÜYH")


def _elided(word: str, next_word: str) -> str:
    if not next_word or next_word[0] not in _FRENCH_ELISION_VOWELS:
        return f"{word} {next_word}"
    prefix = "l" if word.casefold() in ("le", "la") else "d"
    cased = prefix.upper() if word[:1].isupper() else prefix
    return f"{cased}'{next_word}"


def _elide_french_text(text: str) -> str:
    return re.sub(
        r"\b(de|le|la)\s+([^\W\d_]+)",
        lambda m: _elided(m.group(1), m.group(2)),
        text,
        flags=re.IGNORECASE,
    )


def eliding_french(suggestion: TitleSuggestion | None, locale: str) -> TitleSuggestion | None:
    """A model title's "de/le/la + vowel" elided to "d'/l'", in French films only.

    A small model reliably gets the fact right ("de Anne") but not the
    grammar ("de Anne" should read "d'Anne"); this fixes the one thing the
    guard can get right deterministically rather than refusing good facts
    over a spelling rule.
    """
    if suggestion is None or locale != "fr":
        return suggestion
    return replace(
        suggestion,
        title=_elide_french_text(suggestion.title),
        subtitle=_elide_french_text(suggestion.subtitle) if suggestion.subtitle else None,
    )
