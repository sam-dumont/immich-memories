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
    MAKER_POSSESSIVES,
    NOT_A_RELATIONSHIP,
    TYPE_ALIASES,
    UNCONDITIONAL_TYPES,
    RelationWord,
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


# A plausible film year (1900-2100), in any of the 14 film locales (ja/ko/zh
# carry a trailing script character, e.g. "2026年", which this boundary
# ignores since it isn't a digit). Not followed by a unit: "1200 km" or
# "2024 ans" is a distance or an age, never a year, however year-shaped the
# digits are.
_YEAR_DIGITS = re.compile(
    r"(?<!\d)(?:19\d{2}|20\d{2}|2100)(?!\d)"
    r"(?!\s*(?:km|kms|mi|mile|miles|m|cm|€|\$|£|an|ans|yr|yrs|year|years)\b)",
    re.IGNORECASE,
)

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


def refusing_a_wrong_year(
    suggestion: TitleSuggestion | None, start_date: str, end_date: str
) -> TitleSuggestion | None:
    """The suggestion, unless its TITLE names a year outside the memory's own span.

    A person spotlight running 2024-2026 titled "Yuna, été 2021" names a year
    the film never reaches; `requiring_the_year` only checks that the
    required years are present, so a hallucinated extra year passes it. Only
    the headline is checked: a subtitle sometimes carries a day's own date
    (an album name, a special day) that is legitimately outside the span.
    """
    if suggestion is None:
        return suggestion
    start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    for year in (int(y) for y in _YEAR_DIGITS.findall(suggestion.title)):
        if not (start.year <= year <= end.year):
            logger.warning(
                "Title %r (subtitle %r) names %d, outside the span %s to %s; "
                "the template names this memory instead",
                suggestion.title,
                suggestion.subtitle,
                year,
                start_date,
                end_date,
            )
            return None
    return suggestion


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


# Words too small to carry a title's own content: articles, conjunctions,
# possessives, and the handful of "year"/"memories"/"pictures" nouns that
# let a bare year through as a non-answer ("L'année 2025", "Notre année
# 2025", "Souvenirs de 2025", "2025 en images"). Not a stopword list for
# prose -- only what a title's filler commonly is, across the film's
# locales. No "l'année" entry: an apostrophe splits it into "l" and "année"
# before this set is ever consulted, so the fragment list below covers it.
# `_name_words` strips accents (NFKD) before this set is ever consulted, so
# every entry here is written accent-stripped ("annee", not "année") -- an
# accented entry would simply never match anything.
_FILLER_WORDS = frozenset(
    {
        "annee", "notre", "nos", "mon", "ma", "le", "la", "les", "un", "une", "des", "de", "du",
        "et", "en", "images", "image", "souvenir", "souvenirs", "voyage",
        # Fragments an elided "l'/d'/qu'/..." splits off (apostrophe is not a word character).
        "l", "d", "j", "qu", "n", "s", "c",
        "the", "a", "an", "and", "of", "in", "our", "my", "year", "memories", "pictures",
        "photos", "trip", "journey",
        "el", "los", "las", "y", "mi", "mis", "ano", "nuestro", "nuestra", "recuerdos",
        "imagenes", "fotos", "viaje",
        "der", "die", "das", "und", "im", "mein", "meine", "jahr", "unser", "unsere",
        "erinnerungen", "bilder", "reise",
        "il", "lo", "gli", "e", "mio", "mia", "anno", "nostro", "nostra", "ricordi",
        "immagini", "foto", "viaggio",
        "het", "een", "mijn", "jaar", "onze", "herinneringen", "beelden", "reis",
        "o", "os", "as", "meu", "minha", "nosso", "nossa", "lembrancas", "imagens", "viagem",
        "rok", "roku", "i", "moj", "moja", "nasz", "nasza", "wspomnienia", "zdjecia", "podroz",
        "ar", "och", "ett", "min", "mitt", "var", "vart", "minnen", "resa",
        "год", "мой", "моя", "наш", "наша", "воспоминания", "фото",
        "年", "思い出",
        "추억",
        "回忆",
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
    """Every relation type `name` holds to another named person in the film.

    A relation to the film's maker (a role, or a kind pointing at the owner)
    never counts here: the prompt forbids stating one, so it must not also
    be able to back a word's use -- "<child>, le fils" would otherwise pass
    on a maker-only record with nobody else named in the film at all.
    """
    from immich_memories.people.relationships import owner_role

    for rel in context.relationships:
        if rel.target_name in names_in_film:
            type_word = owner_role(rel.kind) or rel.kind.replace("-of", "").replace("-", " ")
            holders.setdefault(type_word.casefold(), set()).add(name)


def _recorded_relation_people(
    person_names: Sequence[str], people_store: Store | None
) -> dict[str, set[str]]:
    """Relation type -> which of the film's people hold it, to each other only."""
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


def _relationship_word_spans(lowered: str, folded_word: str) -> list[tuple[int, int]]:
    """Every place `folded_word` occurs in `lowered`, as its own token or phrase."""
    if _NO_WORD_BOUNDARY_SCRIPT.search(folded_word):
        pattern = re.escape(folded_word)
    else:
        pattern = rf"(?<![\w-]){re.escape(folded_word)}(?![\w-])"
    return [m.span() for m in re.finditer(pattern, lowered)]


def _inside_consumed(span: tuple[int, int], consumed: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(a <= start and end <= b for a, b in consumed)


def _relation_types(relation_type: str) -> tuple[str, ...]:
    """`relation_type` plus whatever generic or paired type backs the same claim.

    The stored record is often gender-neutral (sibling-of, godparent-of,
    parent-of) where a title writes the specific word (brother, godmother,
    mother); either direction counts as the same relation.
    """
    return (relation_type, *TYPE_ALIASES.get(relation_type, ()))


def _word_is_unfounded(relation_type: str, plural: bool, holders: dict[str, set[str]]) -> bool:
    # WHY: "Noël en famille" names no one; a bare "family" word is a mood,
    # not a claim about a specific person, so it is never refused for want
    # of a record -- unlike "famille" paired with an actual relation word.
    if relation_type == FAMILY_GENERIC or relation_type in UNCONDITIONAL_TYPES:
        return False
    people: set[str] = set()
    for the_type in _relation_types(relation_type):
        people |= holders.get(the_type, set())
    return not people or (plural and len(people) < 2)


def _name_tokens(person_names: Sequence[str]) -> frozenset[str]:
    return frozenset(w.casefold() for name in person_names for w in _name_words(name))


# How many of the words right before a relationship word are checked for a
# maker possessive: "our daughter" or "our little daughter" both count.
_MAKER_POSSESSIVE_WINDOW = 3
# How many characters before a CJK relationship word are checked: these
# scripts carry no spaces, so a token count means nothing.
_MAKER_POSSESSIVE_CJK_WINDOW = 6


def _preceded_by_maker_possessive(lowered: str, start: int, locale: str) -> bool:
    """Whether a nearby word before `start` speaks as the film's maker ("our", "notre").

    Split on whitespace only, never through `_name_words`: that helper
    folds away accents for name matching, which would silently stop "mój"
    or "vår" from ever being recognised as themselves.
    """
    markers = MAKER_POSSESSIVES.get(locale, frozenset())
    if not markers:
        return False
    before = lowered[:start]
    if _NO_WORD_BOUNDARY_SCRIPT.search("".join(markers)):
        window = before[-_MAKER_POSSESSIVE_CJK_WINDOW:]
        return any(marker in window for marker in markers)
    tokens = [t.strip(".,;:!?'’\"") for t in before.split()]
    tokens = [t for t in tokens if t]
    return any(tok in markers for tok in tokens[-_MAKER_POSSESSIVE_WINDOW:])


def _occurrence_is_refused(
    span: tuple[int, int],
    entry: RelationWord,
    lowered: str,
    holders: dict[str, set[str]],
    locale: str,
) -> bool:
    relation_type, plural, perspective = entry
    if relation_type == NOT_A_RELATIONSHIP:
        return False
    if perspective or _preceded_by_maker_possessive(lowered, span[0], locale):
        return True
    return _word_is_unfounded(relation_type, plural, holders)


# Swedish "far" is also the everyday verb "to travel" ("vi far till Rom");
# only a possessive or a name right before it reads it as "father".
_SV_FAR_NEARBY_POSSESSIVES = frozenset({"vår", "vårt", "hans", "hennes", "sin", "sitt", "min", "mitt"})  # fmt: skip


def _sv_far_is_the_verb(
    folded: str, lowered: str, span: tuple[int, int], locale: str, known_names: frozenset[str]
) -> bool:
    if locale != "sv" or folded != "far":
        return False
    tokens = [t.strip(".,;:!?'’\"") for t in lowered[: span[0]].split()]
    tokens = [t for t in tokens if t]
    nearby = tokens[-_MAKER_POSSESSIVE_WINDOW:]
    return not any(tok in _SV_FAR_NEARBY_POSSESSIVES or tok in known_names for tok in nearby)


def _unfounded_relationship_word(
    text: str,
    words: dict[str, RelationWord],
    holders: dict[str, set[str]],
    known_names: frozenset[str],
    locale: str,
) -> str | None:
    """The first relationship word in `text` the title may not use, if any.

    Checked longest phrase first, and a shorter word's match is skipped once
    it falls entirely inside a longer phrase already accounted for -- so
    "meilleur ami" is read whole rather than also flagging "ami" inside it.
    A word that is one of the film's own first names is never a relation
    word. A word spoken as the maker's own ("our daughter") is refused
    outright: it states a relationship to the film's maker, which the
    prompt forbids. A friend may always be named as a friend; a perspective
    word (maman, papy, mum, oma) is refused outright, record or no record --
    it narrates from a child's point of view, which the template never does.
    Every other word still needs that record: refused when the relation it
    names is not among the film's own recorded relations, or a plural word
    covers only one person.
    """
    lowered = text.casefold()
    consumed: list[tuple[int, int]] = []
    for word, entry in sorted(words.items(), key=lambda kv: -len(kv[0])):
        folded = word.casefold()
        if folded in known_names:
            continue
        for span in _relationship_word_spans(lowered, folded):
            if _inside_consumed(span, consumed):
                continue
            consumed.append(span)
            if _sv_far_is_the_verb(folded, lowered, span, locale, known_names):
                continue
            if _occurrence_is_refused(span, entry, lowered, holders, locale):
                return word
    return None


def refusing_unfounded_relationships(
    suggestion: TitleSuggestion | None,
    person_names: Sequence[str],
    locale: str,
    people_store: Store | None,
    holiday: str | None = None,
) -> TitleSuggestion | None:
    """The suggestion, minus a relationship word the family record does not back.

    A relationship word is backed when the recorded relations between the
    film's own people include that relation type, for at least as many
    people as the word's grammatical number claims. A friend called "le
    fils" of parents who are not in the film, or one grandchild called "les
    petits-enfants", falls back to the template; an unfounded word in the
    subtitle alone only drops the subtitle. A holiday film ("Fête des
    mères", "Muttertag") is left alone entirely: the prompt names the
    holiday by itself, which is naming the day, not a specific person.
    """
    if suggestion is None or holiday:
        return suggestion
    words = relationship_words(locale)
    holders = _recorded_relation_people(person_names, people_store)
    known_names = _name_tokens(person_names)
    if bad := _unfounded_relationship_word(suggestion.title, words, holders, known_names, locale):
        logger.warning(
            "Title %r calls somebody %r, a relation the family record does not back; "
            "the template names this memory instead",
            suggestion.title,
            bad,
        )
        return None
    if suggestion.subtitle and (
        bad := _unfounded_relationship_word(
            suggestion.subtitle, words, holders, known_names, locale
        )
    ):
        logger.info("Subtitle calls somebody %r, which the family record does not back", bad)
        return replace(suggestion, subtitle=None)
    return suggestion


# No "y"/"Y": French treats an initial y as a consonant in most everyday
# words and names ("le yaourt", "Yokohama", "Yuna"), so it never elides.
_FRENCH_ELISION_VOWELS = frozenset("aàâeéèêëiîïoôuùûühAÀÂEÉÈÊËIÎÏOÔUÙÛÜH")

# h aspiré: well-known place names and common nouns that keep their "h" as a
# consonant ("le Havre", never "l'Havre"). Lexical, not a rule -- only the
# exceptions a title is likely to actually name are listed. "Hérault" looks
# the same shape but is h muet in common usage ("l'Hérault"), so it is kept
# off this list rather than added to it.
_FRENCH_ASPIRATED_H_PLACES = frozenset(
    {
        "havre", "haye", "havane", "hulpe", "hainaut", "hollande", "hongrie",
        "huy", "hasselt", "hambourg", "honduras", "hanovre", "helsinki",
        "hawaï", "hawai", "himalaya", "hongkong",
    }
)  # fmt: skip
_FRENCH_ASPIRATED_H_COMMON_NOUNS = frozenset(
    {"haricot", "haricots", "hibou", "hiboux", "héros", "hockey", "honte", "hutte"}
)
# A capitalised H name not on the aspiré list above is still not elided by
# default: "when unsure, don't elide" a proper noun. Only a name confirmed
# h muet in common usage (Hérault) is exempted from that caution.
_FRENCH_ELIDABLE_H_NAMES = frozenset({"hérault"})


def _elided(word: str, next_word: str) -> str:
    if not next_word or next_word[0] not in _FRENCH_ELISION_VOWELS:
        return f"{word} {next_word}"
    folded = next_word.casefold()
    if folded in _FRENCH_ASPIRATED_H_PLACES or folded in _FRENCH_ASPIRATED_H_COMMON_NOUNS:
        return f"{word} {next_word}"
    if (
        next_word[0].casefold() == "h"
        and next_word[:1].isupper()
        and folded not in _FRENCH_ELIDABLE_H_NAMES
    ):
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
