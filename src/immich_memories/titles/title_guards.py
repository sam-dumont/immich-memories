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
from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from difflib import SequenceMatcher
from functools import lru_cache

from immich_memories.titles.relationship_words import name_words
from immich_memories.titles.title_routing import is_trip
from immich_memories.titles.title_suggestion import TitleSuggestion

logger = logging.getLogger(__name__)

# Languages spell the same place their own way (Brussels/Bruxelles,
# Gent/Ghent), so a name the facts carry and a name the title writes are the
# same name when they are this close, and different names below it.
_SAME_NAME_RATIO = 0.6

_name_words = name_words


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
    # An all-capitals word is the condition's own AND/OR, never a name to capitalise.
    names = {
        word.casefold()
        for word in _name_words(facts)
        if word[:1].isupper() and len(word) > 2 and not word.isupper()
    }

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


# A subtitle word must match a backing word this closely; a name may be spelled another way
# in another language (`_SAME_NAME_RATIO`), a plain word may only be inflected.
_SAME_WORD_RATIO = 0.85
# Shorter words are articles, prepositions and numbers' suffixes, not a mood.
_MIN_CHECKED_WORD = 4


def _unbacked_word(line: str, backing: set[str]) -> str | None:
    """The first word of `line` that is neither a date, a place, a name nor backed by a fact."""
    for word in _name_words(line):
        folded = word.casefold()
        if (
            len(folded) < _MIN_CHECKED_WORD
            or not word.isalpha()
            or folded in _FILLER_WORDS
            or folded in _calendar_words()
            or folded in _one_word_places()
            or folded in backing
        ):
            continue
        if any(
            SequenceMatcher(None, folded, known).ratio() >= _SAME_WORD_RATIO for known in backing
        ):
            continue
        return word
    return None


def refusing_unbacked_subtitle(
    suggestion: TitleSuggestion | None,
    facts: str,
    memory_type: str,
    start_date: str,
    end_date: str,
    person_names: Sequence[str],
    locale: str,
) -> TitleSuggestion | None:
    """The suggestion, minus a subtitle that names a quality or a mood nothing in the film backs.

    A subtitle may carry dates, places and people, and the words the facts or the template
    title themselves use. "Salt air and golden light" over a trip film is decoration no
    fact supports, so the subtitle goes and the title stands.
    """
    if suggestion is None or not suggestion.subtitle or not facts:
        return suggestion
    template = _template_title_text(
        memory_type,
        date.fromisoformat(start_date),
        date.fromisoformat(end_date),
        person_names,
        locale,
    )
    backing = {word.casefold() for word in _name_words(f"{facts} {template}")}
    if unbacked := _unbacked_word(suggestion.subtitle, backing):
        logger.info(
            "Subtitle uses %r, which no fact in the film backs; dropping the subtitle", unbacked
        )
        return replace(suggestion, subtitle=None)
    return suggestion


# A year or a year range closing a title, set off from the words before it only by a space.
_TRAILING_YEARS = re.compile(
    r"(?<=[^\W\d_])\s+(?P<years>(?:19|20)\d{2}(?:\s*[-\u2013\u2014]\s*(?:19|20)?\d{2})?)\s*$"
)
_YEAR_SEPARATOR = " \u00b7 "


def separating_the_years(
    suggestion: TitleSuggestion | None, person_names: Sequence[str]
) -> TitleSuggestion | None:
    """A title of several names and a year range sets the years off with a separator.

    "Anna, Ben, Chloé et Dan 2013-2026" runs the years into the last name; a
    middle dot reads the same in every film language and needs no translation.
    A single name keeps its years as the model wrote them.
    """
    if suggestion is None or len(person_names) < 2:
        return suggestion
    match = _TRAILING_YEARS.search(suggestion.title)
    if match is None:
        return suggestion
    title = suggestion.title[: match.start()] + _YEAR_SEPARATOR + match["years"]
    return replace(suggestion, title=title)


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
    r"(?!\s*(?:km|kms|mi|mile|miles|m|cm|an|ans|yr|yrs|year|years)\b)"
    # Currency symbols have no word boundary of their own, so they are
    # excluded separately rather than folded into the `\b`-terminated
    # alternation above (a trailing `\b` after "€" never matches at all).
    r"(?!\s*[€$£])",
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
        "年", "思い出", "の",
        "추억",
        "回忆",
    }
)  # fmt: skip

# Japanese, Korean and Chinese write these filler words with no space
# around them ("2025年の思い出"), so a word-bag split never isolates them;
# removing them as substrings first lets the rest tokenise normally.
_CJK_FILLER_SUBSTRINGS = ("年", "思い出", "の", "추억", "回忆")


def _content_words(text: str) -> set[str]:
    """The words of `text` that are not filler: what the title actually says."""
    stripped = text
    for substring in _CJK_FILLER_SUBSTRINGS:
        stripped = stripped.replace(substring, " ")
    return {w.casefold() for w in _name_words(stripped) if w.casefold() not in _FILLER_WORDS}


# The generic album-copy shape ("Mon voyage en images - Paris", "Our trip in
# pictures", "Unsere Reise in Bildern"): a possessive, a word for "trip", and
# a word for "in pictures", with or without a place tacked on after a dash.
# This is filler as a whole PHRASE even with a place on it -- it is the
# template a photo album already writes by default, not a title.
_ALBUM_COPY_SHAPE = re.compile(
    r"^(?:(?:notre|nos|mon|ma|our|my|unser|unsere|mein|meine|nuestro|nuestra|mi|mis|"
    r"nostro|nostra|mio|mia|ons|onze|nosso|nossa|meu|minha)\s+)?"
    r"(?:voyage|trip|reis|reise|viaje|viaggio|viagem|podróż|resa)\s+"
    r"(?:en images|in pictures|in bildern|in beelden|em imagens|in immagini)"
    r"(?:\s*[-–—:]\s*.+)?$",
    re.IGNORECASE,
)


def _is_album_copy_shape(title: str) -> bool:
    return bool(_ALBUM_COPY_SHAPE.match(title.strip()))


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
    template names the same year more plainly, so it wins. The album-copy
    shape ("Notre voyage en images - Paris") is refused even with a place
    on it: it is a photo album's own default caption, not a crafted title.
    """
    if suggestion is None:
        return suggestion
    if _is_album_copy_shape(suggestion.title):
        logger.info(
            "Title %r is the album-copy shape, not a crafted title; "
            "the template names this memory instead",
            suggestion.title,
        )
        return None
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
_FRENCH_ELIDABLE_H_NAMES = frozenset({"hérault", "hélène"})


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
