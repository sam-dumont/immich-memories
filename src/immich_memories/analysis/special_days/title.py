"""What a day may be called, and what to call it when the model's answer cannot be.

The model writes the title; this decides whether the day can support it. Asked
about a night out with no city and no GPS anywhere in it, the model answered
with three names and a town — the names real, the town invented — and a title
card is the wrong place for a plausible invention.

Dropping the invention is only half the job. A 2010 scan put days in the
catalogue titled "Six images captured between 07:32 and 16:06, tracing a route
from weathered apar": the day's own description, cut at eighty characters and
wearing a title's hat, because the drop left nothing else to show. So a dropped
title is asked for once more, and what is kept after that is the plainest true
thing the day still knows — where it was, or what it was. There is no
date-derived last resort here on purpose: the date is already on the card, and
a day nothing can name is a day the catalogue is better off not keeping.
"""

from __future__ import annotations

import collections
import logging
import re
import unicodedata
from collections.abc import Sequence, Set
from functools import lru_cache

from immich_memories.i18n import (
    LANGUAGE_NAMES,
    babel_locale,
    elide_french,
    film_text,
    spoken_list,
)

logger = logging.getLogger(__name__)

# Capitalised words a title may use without naming anything: sentence starts,
# the calendar, and the few verbs an English title puts after "to" — "A Day to
# Remember" was blanked for never having been to a place called Remember.
# Anything else has to come from the day itself. The verb list will never be
# complete, and does not need to be: what it misses is a blanked title, which
# is visible, rather than an invented one, which is not.
_EVERYDAY_CAPITALS = {
    "a",
    "an",
    "the",
    "and",
    "with",
    "at",
    "in",
    "on",
    "of",
    "to",
    "from",
    "for",
    "remember",
    "forget",
    "celebrate",
    "cherish",
    "treasure",
    "behold",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "morning",
    "afternoon",
    "evening",
    "night",
    "day",
    "birthday",
    "wedding",
    "christmas",
    "easter",
    "new",
    "year",
    "eve",
}

# The words of a title, as every check here splits it.
_WORD = r"[\w\u00c0-\u024f]+"
# Holiday names barely change; these years hold every one a calendar names.
_HOLIDAY_YEARS = range(2000, 2031)


def title_the_day_can_keep(written: str, assets: list, *, evidence: str, locale: str = "en") -> str:
    """The model's title, or nothing if the day cannot support it.

    `locale` is the language the title was asked in: its month, weekday and public holiday
    names are as plain as their English ones ("Le réveillon de Noël" names no place).
    """
    if len(written.split()) > 8 or len(written) > 60 or _A_CLOCK.search(written):
        return ""
    people = _named_people(assets)
    return _only_if_grounded(
        written if _is_a_real_title(written, people, locale) else "", assets, evidence, locale
    )


def line_the_day_can_keep(written: str, assets: list, *, evidence: str, locale: str = "en") -> str:
    """The line under the title, held to the same rule as the title."""
    return _only_if_grounded(written, assets, evidence, locale)


def honest_title(assets: list, *, what: str, evidence: str, locale: str = "en") -> str:
    """What to call a day whose own title was dropped, or nothing.

    The place comes before `what` because it is the checked signal: it is read
    off the day's own EXIF, while `what` is another line of the same answer the
    guard just refused. And `what` is only a title when it reads as one — the
    model writes that field as a caption as readily as a name, and the
    description it wrote for a day in 2010 is what put a truncated sentence on
    a title card in the first place.

    Nothing at all is a valid answer. A day the library cannot name honestly is
    refused rather than rendered under a generic date, here as everywhere else.
    """
    if not what:
        return ""
    if found := place_and_kind_from_assets(assets):
        return day_in_place(*found, locale)
    if not _reads_as_a_title(what):
        return ""
    return title_the_day_can_keep(what, assets, evidence=evidence, locale=locale)


def birth_title(born: Sequence[str], locale: str) -> str:
    """The day these people were born, as the film's language names a birth, or nothing.

    The registry's birth date is the evidence: on that day the occasion is the birth, whatever
    else the pictures show ("Naissance de Kit", "The birth of Kit").
    """
    if not born:
        return ""
    named = film_text("title.birth", locale, name=spoken_list(list(born), locale))
    return elide_french(named) if locale == "fr" else named


def day_in_place(place_name: str, kind: str, locale: str) -> str:
    """ "A day in {place}" with the right preposition, never a wrong one.

    Reuses the trip machinery (`place_phrases`): a language with a rule for
    this place's kind gets a proper phrase ("en France", "we Włoszech"); a
    language or a place with none (Polish/Russian/Japanese/Chinese/Korean do
    not cover every city and region, and some locales have no module at all)
    gets the neutral form with no preposition at all, place first -- the same
    rule the trip title follows (see `_trip_titles.generate_trip_title`).
    """
    from immich_memories.i18n_places import localise_country, localise_place
    from immich_memories.place_phrases import Place, place_phrase

    if phrase := place_phrase(locale, Place(place_name, kind)):
        return film_text("title.day_in_place_with", locale, phrase=phrase)
    localised = (
        localise_country(place_name, locale)
        if kind == "country"
        else (localise_place(place_name, locale) or place_name)
    )
    return film_text("title.day_in_place_neutral", locale, place=localised)


def title_language(locale: str) -> str:
    """The language a day's title is asked for in, as the title prompts name it."""
    return LANGUAGE_NAMES.get(locale, LANGUAGE_NAMES["en"])


def retitle_prompt(lines: str, *, rejected: str, assets: list, locale: str = "en") -> str:
    """Ask again for a title, saying what the last one claimed and what a title may claim.

    Told once, positively, rather than handed the growing list of things not to
    say: the model usually can write a grounded title on a second try, and the
    thing it got wrong is worth naming because it is the thing it is otherwise
    about to write again.
    """
    unplaced = (
        ""
        if _knows_where_it_was(assets)
        else "\nNothing on this day records where it was, so no place name can be right.\n"
    )
    return _RETITLE_PROMPT.format(
        lines=lines, rejected=rejected, unplaced=unplaced, language=title_language(locale)
    )


# The day's lines and the rejected title are last, so the instruction above them is one
# byte-identical prefix across every retitle (#981).
_RETITLE_PROMPT = """The same day again, one line per picture, in the order they were taken.

Write another title for it. A first one was written and put aside because it claims
something the lines do not show. Every specific in the new one — a place, a distance, a
count, a name — comes from those lines: write what they show, as concretely as they show
it, and nothing more. Not the date and not a name on its own; both are already on the card.
Write it in {language}.

Answer with STRICT JSON only, no prose:
{{"title": "<a few words>"}}
{unplaced}
PUT ASIDE: "{rejected}"

{lines}"""


# A title is a few words; the day's description is a sentence. The model writes
# `what` as either, and the sentence is what reached the catalogue as a title:
# "Six images captured between 07:32 and 16:06, tracing a route from weathered
# apar" is the day described, truncated, and it is 12 words with a clock in it.
_TITLE_WORDS = 6
_A_CLOCK = re.compile(r"\d{1,2}:\d{2}")


def _reads_as_a_title(text: str) -> bool:
    words = text.split()
    return bool(words) and len(words) <= _TITLE_WORDS and not _A_CLOCK.search(text)


# A day's EXIF field, and the `place_phrases.Place` kind the same word names:
# a city is a city, a state is the closest thing EXIF has to a region, and a
# bare country name is a country -- so the film-time fallback can pick the
# right preposition instead of guessing one from the string alone.
_EXIF_PLACE_KINDS = (("city", "city"), ("state", "region"), ("country", "country"))


def place_and_kind_from_assets(assets: list) -> tuple[str, str] | None:
    """The place the day's own pictures name most often, and what kind it is.

    Coordinates are not a place name: a day with GPS and no city has nowhere
    this can name, and inventing one from the numbers is the failure the guard
    above exists for. Public because the film-time title falls back to the same
    reading of a day's own EXIF when no model is there to translate the catalogue's
    English title (see ``titles.film_title``).
    """
    for attr, kind in _EXIF_PLACE_KINDS:
        names = collections.Counter(
            str(value)
            for asset in assets
            if (value := getattr(getattr(asset, "exif_info", None), attr, None))
        )
        if names:
            return names.most_common(1)[0][0], kind
    return None


def _named_people(assets: list) -> set[str]:
    return {
        person.name.casefold()
        for asset in assets
        for person in (getattr(asset, "people", None) or [])
        if getattr(person, "name", "")
    }


def _people_words(assets: list) -> set[str]:
    """Every word of every name on the day's pictures, folded."""
    return {word for name in _named_people(assets) for word in re.findall(_WORD, name)}


def _fold(word: str) -> str:
    """A word as the calendar lists compare it: folded, accents away ("Août" is "aout")."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", word.casefold()) if not unicodedata.combining(c)
    )


def _english(locale: str) -> bool:
    return babel_locale(locale).language == "en"


@lru_cache(maxsize=16)
def _everyday_capitals(locale: str) -> frozenset[str]:
    """The capitalised words a title in `locale`'s language may use without naming anything,
    folded (`_fold`).

    The English list, and in any other language that language's month and weekday names and
    its public holidays: on a French catalogue "Le réveillon de Noël" was dropped for a day
    never in a place called Noël. English keeps its own list alone, because the calendars it
    would add name people and places ("Washington's Birthday", "Columbus Day").
    """
    if _english(locale):
        return frozenset(_EVERYDAY_CAPITALS)
    from immich_memories.titles.title_guards import calendar_words_in

    return frozenset(_EVERYDAY_CAPITALS) | calendar_words_in(locale) | _holiday_words(locale)


def _is_everyday(word: str, locale: str) -> bool:
    return _fold(word) in _everyday_capitals(locale)


@lru_cache(maxsize=16)
def _holiday_words(locale: str) -> frozenset[str]:
    """The words of the public holidays a calendar names in `locale`'s language.

    The calendar is the language's own country's ("fr" is France's, "pt-BR" Brazil's), the
    way the app's holidays come from the `holidays` package. A country whose calendar does
    not speak the language adds nothing.
    """
    import holidays as calendars
    from babel.core import get_global

    where = babel_locale(locale)
    likely = str(get_global("likely_subtags").get(where.language, ""))
    country = where.territory or (likely.rsplit("_", 1)[-1] if "_" in likely else "")
    try:
        supported = calendars.country_holidays(country, years=2020).supported_languages
    except NotImplementedError:
        return frozenset()
    spoken = [code for code in supported if code.split("_")[0] == where.language]
    if not spoken:
        return frozenset()
    names = calendars.country_holidays(country, years=_HOLIDAY_YEARS, language=spoken[0])
    return frozenset(_fold(word) for name in names.values() for word in re.findall(_WORD, name))


def _place_vocabulary(assets: list) -> set[str]:
    """Every place name the day recorded, or empty if it recorded none."""
    words: set[str] = set()
    for asset in assets:
        exif = getattr(asset, "exif_info", None)
        for attr in ("city", "state", "country"):
            value = getattr(exif, attr, None) if exif else None
            if value:
                words.update(re.findall(r"[\w\u00c0-\u024f]+", str(value)))
    return {w.casefold() for w in words}


def _grounding_vocabulary(assets: list) -> set[str]:
    """Every proper noun the model was given: the places, and who was there."""
    words = _place_vocabulary(assets).copy()
    for asset in assets:
        for person in getattr(asset, "people", None) or []:
            if getattr(person, "name", ""):
                words.update(w.casefold() for w in re.findall(r"[\w\u00c0-\u024f]+", person.name))
    return words


def _knows_where_it_was(assets: list) -> bool:
    """Did anything tell us where this day happened?"""
    for asset in assets:
        exif = getattr(asset, "exif_info", None)
        if not exif:
            continue
        if getattr(exif, "city", None) or getattr(exif, "country", None):
            return True
        if getattr(exif, "latitude", None) and getattr(exif, "longitude", None):
            return True
    return False


def _is_a_real_title(text: str, people: set[str], locale: str = "en") -> bool:
    """Reject the two things the model falls back on when it is unsure.

    Asked to prefer the plain true thing, it starts answering with the one
    fact it is certain of: "Monday 13 August 2007", or simply a
    person's name. Both are already on the card. Seven of twenty-three titles in a
    library sweep came back like that. A date in the title's own language
    ("Lundi 13 août") is the same date.
    """
    if not text:
        return False
    stripped = re.sub(
        r"[\d,]|\b(mon|tues|wednes|thurs|fri|satur|sun)day\b", "", text, flags=re.IGNORECASE
    )
    stripped = re.sub(
        r"\b(january|february|march|april|may|june|july|august|september|october"
        r"|november|december|at|in|on|the|of)\b",
        "",
        stripped,
        flags=re.IGNORECASE,
    )
    if not _english(locale):
        from immich_memories.titles.title_guards import calendar_words_in

        calendar = calendar_words_in(locale)
        stripped = " ".join(
            word for word in re.findall(_WORD, stripped) if _fold(word) not in calendar
        )
    if not stripped.strip():
        return False
    return text.casefold() not in people


# How close a written place has to be to one the day recorded. EXIF is in the
# local language and the model writes English: a local spelling and its English form are the
# same place and must pass.
#
# A ratio cannot also separate two different towns, and measuring says so: two
# neighbouring towns twelve kilometres apart score 0.750 while a city and its
# other-language name score 0.706, and two more pairs — one the same city in
# two languages, one two unrelated cities — both score 0.600. There is no
# cutoff that gets all four right. What the check is actually for is the
# invention, and an invented famous place bears no resemblance to anything the
# day recorded at all, so it fails at any cutoff in this range. Set low enough
# to keep real titles, then, and do not tighten it believing it can do more.
_SAME_PLACE_RATIO = 0.70

# French "de" names a place as often as a person ("Circuit de ...", "Anniversaire de ..."): a
# candidate made only of the day's people's names is a person (`_place_it_was_never_in`).
_PLACE_PREPOSITIONS = ("in", "at", "near", "around", "from", "to", "de", "outside", "à", "au", "en")


def _named_places(text: str, locale: str = "en") -> list[str]:
    """Capitalised words used as somewhere, rather than as something.

    "to" introduces a destination as readily as it introduces a verb, and in
    a title both are capitalised: "A Day to Remember" was blanked for having
    never been to a place called Remember. So a candidate made only of words
    a title may use without naming anything is not a place claim — which is
    what _EVERYDAY_CAPITALS has always been for — and "to" stays, because
    dropping it left a located day with no guard on place claims at all.
    """
    pattern = (
        r"\b(?:" + "|".join(_PLACE_PREPOSITIONS) + r")\s+"
        r"((?:[A-Z\u00c0-\u00dd][\w\u00c0-\u024f'-]+(?:[ -](?:de|la|le|sur|of|the))?\s*){1,3})"
    )
    found = [m.strip() for m in re.findall(pattern, text)]
    return [
        place
        for place in found
        if not all(_is_everyday(word, locale) for word in re.findall(_WORD, place))
    ]


def _place_is_real(place: str, vocabulary: set[str]) -> bool:
    """Did the day actually happen anywhere by this name?"""
    import difflib

    for word in re.findall(r"[\w\u00c0-\u024f]+", place):
        if len(word) < 4:
            continue
        if difflib.get_close_matches(
            word.casefold(), list(vocabulary), n=1, cutoff=_SAME_PLACE_RATIO
        ):
            return True
    return False


# Distances and the races named after one. Both are claims a title makes as
# flatly as it names a place, and both read as true whether or not the day
# recorded anything of the kind.
_QUANTITY = re.compile(
    r"\b\d+\s?(?:k|km|mi|miles?)\b|\b(?:marathon|triathlon|ironman|ultra)\b",
    re.IGNORECASE,
)


def _same_quantity(written: str) -> str:
    """ "20 km" and "20km" are one claim, written twice."""
    return re.sub(r"\s+", "", written).casefold()


def _unsupported_quantity(text: str, evidence: str) -> str | None:
    """A distance or a race the lines the model was given never mention.

    Asked about a morning of running whose evidence says only that there were
    runners in numbered bibs, the model answered with a specific distance. The
    place guard had nothing to say about it — it only ever read places — and a
    number is a claim of exactly the same kind.
    """
    supported = {_same_quantity(q) for q in _QUANTITY.findall(evidence)}
    return next((q for q in _QUANTITY.findall(text) if _same_quantity(q) not in supported), None)


def _only_if_grounded(text: str, assets: list, evidence: str, locale: str = "en") -> str:
    """Drop a line whose specifics the day cannot support.

    Asked about a night out with no city and no GPS anywhere in it, the model
    answered with three names and a town. The names were real
    and a place was invented, in spite of the prompt forbidding it. A title card
    is the wrong place for a plausible invention.

    The capitalised-word check only applies when the day carries no location at
    all. Given coordinates, naming the circuit they sit on is inference from
    data, and an earlier version that policed every capitalised word threw away
    "Audi R8 V10 Track Day at a place" — a correct reading of the pictures —
    because no EXIF field happens to contain the word Audi.
    """
    # A number nothing on the day mentions. This one runs on every day,
    # located or not: a distance is not inference from coordinates the way a
    # circuit's name is, and the prompt asking for it costs nothing to ignore.
    if unsupported := _unsupported_quantity(text, evidence):
        logger.info("Dropping %r: nothing on this day mentions %r", text, unsupported)
        return ""

    places = _place_vocabulary(assets)
    if place := _place_it_was_never_in(text, places, _people_words(assets), locale):
        logger.info("Dropping %r: the day was never in %r", text, place)
        return ""

    vocabulary = _grounding_vocabulary(assets)
    if coined := _guessed_name(text, vocabulary):
        logger.info("Dropping %r: %r looks like a guessed name", text, coined)
        return ""

    if not text or _knows_where_it_was(assets):
        return text

    # On a day with no location at all, every capitalised word has to come
    # from the day itself \u2014 except the first, which is capitalised because it
    # opens the line. "Children's camp activities" claims nothing, and dropping
    # it for that C is how a day ends up with no title to show at all.
    for found in re.finditer(r"\b[A-Z\u00c0-\u00dd][\w\u00c0-\u024f'-]{2,}", text):
        word = found.group()
        if found.start() == 0:
            continue
        if word.casefold() not in vocabulary and not _is_everyday(word, locale):
            logger.info(
                "Dropping title %r: the day has no location and nothing mentions %r", text, word
            )
            return ""
    return text


def _place_it_was_never_in(
    text: str, places: set[str], people: Set[str] = frozenset(), locale: str = "en"
) -> str | None:
    """A place the day never recorded.

    Asked about a track day at a place — with three villages all in its EXIF —
    the model answered "the famous circuit", Belgium's famous circuit rather
    than the one the coordinates sit on. Recognising the kind of place and
    naming the well-known instance of it is the failure that keeps recurring.

    Only when the day recorded place names at all: with coordinates and no
    city, naming the circuit they sit on is inference this cannot check, and
    rejecting it would throw away the model's best work.

    A candidate made only of the names of people on the day's pictures is one of them, not a
    place: "Anniversaire de Kit" says whose birthday it was. Read as a place, it was 38 of the
    39 French titles the guard dropped on a stored catalogue.
    """
    if not places:
        return None
    return next(
        (
            p
            for p in _named_places(text, locale)
            if not all(word.casefold() in people for word in re.findall(_WORD, p))
            and not _place_is_real(p, places)
        ),
        None,
    )


def _guessed_name(text: str, vocabulary: set[str]) -> str | None:
    """A CamelCase name nothing on the day mentions.

    Told twice in the prompt not to name an event it could not read, the model
    answered "Attending KubeCon" and then, the same day, "Attending GitLab
    All-Hands" — a hall full of lanyards, and an invented answer to which
    conference it was. Both of those days knew exactly where they were, so this
    runs before the located early-return or it never runs at all. An internal
    capital is what separates it from Audi, R8 or a place name.
    """
    coined = re.findall(r"\b[A-Z][a-z]+[A-Z][\w]*", text)
    return next((c for c in coined if c.casefold() not in vocabulary), None)
