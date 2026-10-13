"""Common nouns in the film languages that capitalise every noun.

The invented-name guard reads a capital past a title's first word as a name.
German capitalises every noun, so "Robin und Kit im Jahr 2025" carries "Jahr"
as a capital that names nobody. Of the film languages only German does this;
the others capitalise names alone, the way the guard assumes.

The nouns a German title is known to use come from what the app already
writes in German (its own film catalogue: seasons, "Jahr", "Tag", "Woche"),
the relationship words the relationship guard checks on its own, and a short
list of the scenes and occasions a family film is titled after. Holidays are
left out: one is a name the facts must back, in every language. A noun the
list lacks still reads as a name, so the title falls back to the rules title
rather than letting an invented one through.
"""

from __future__ import annotations

import re
from functools import lru_cache

from immich_memories.titles.relationship_words import name_words, relationship_words

# Film languages whose orthography capitalises common nouns, not names alone.
_NOUN_CAPITALISING = frozenset({"de"})

# What a title calls the day: occasions, scenes, places by kind, weather. Folded and accent-free,
# as `name_words` leaves them ("spass", not "Spaß"). Not names: a lake by name ("Bodensee") is
# still a place the facts must carry.
_TITLE_NOUNS: dict[str, frozenset[str]] = {
    "de": frozenset(
        {
            "abend", "abenteuer", "alltag", "ausflug", "bad", "baby", "berg", "bilder", "dorf",
            "erinnerung", "familie", "feier", "ferien", "fest", "foto", "freund", "freundin",
            "garten", "geburt", "geburtstag", "glueck", "haus", "heimat", "hochzeit", "insel",
            "jahrestag", "kindergarten", "kueste", "land", "leben", "liebe", "meer", "moment",
            "morgen", "nacht", "natur", "park", "party", "picknick", "regen", "reise", "schnee",
            "schule", "see", "sonne", "spass", "spiel", "stadt", "strand", "taufe", "tour",
            "urlaub", "wald", "wanderung", "wochenende", "zeit", "zuhause", "zoo",
        }
    ),
}  # fmt: skip

# German plural, dative and genitive endings: "Bergen", "Tage", "Jahres", "Freunden".
_INFLECTIONS = ("e", "n", "en", "er", "ern", "s", "es", "nen")
# A catalogue template's slots ("{season} {year}") are English field names, not German.
_SLOT = re.compile(r"\{[^}]*\}")
# A shorter stem plus an ending reads as too many names ("Bad" + "en").
_MIN_INFLECTED_STEM = 4


def _catalogue_words(locale: str, left_out: tuple[str, ...]) -> frozenset[str]:
    """The folded words of `locale`'s own film-text templates, but those of `left_out` keys."""
    from immich_memories.i18n import film_texts

    return frozenset(
        w.casefold()
        for key, forms in film_texts(locale).items()
        if not key.startswith(left_out)
        for form in forms
        for w in name_words(_SLOT.sub(" ", form))
    )


@lru_cache(maxsize=16)
def own_words(locale: str) -> frozenset[str]:
    """Every word the app itself writes in `locale`'s film text, folded: its titles, story
    names and the summary's joining words ("puis", "jours", "maison" in French).

    Holidays and seasons are left out: each names a day or a period the facts must back, in
    every language ("Winter" over a summer film is wrong, not filler).
    """
    return _catalogue_words(locale, ("holiday.", "season."))


@lru_cache(maxsize=16)
def _nouns(locale: str) -> frozenset[str]:
    # A season is a common noun to German orthography ("im Sommer"), a holiday is a name.
    words = set(_TITLE_NOUNS.get(locale, frozenset())) | _catalogue_words(locale, ("holiday.",))
    for relation in relationship_words(locale):
        if len(folded := name_words(relation)) == 1:
            words.add(folded[0].casefold())
    return frozenset(words)


def is_a_common_noun(word: str, locale: str) -> bool:
    """Whether `word` is a common noun `locale` capitalises, so its capital names nobody.

    Always False in a language that capitalises names alone.
    """
    if locale not in _NOUN_CAPITALISING:
        return False
    folded = next(iter(name_words(word)), "").casefold()
    nouns = _nouns(locale)
    if folded in nouns:
        return True
    return any(
        folded.endswith(ending)
        and len(stem := folded[: len(folded) - len(ending)]) >= _MIN_INFLECTED_STEM
        and stem in nouns
        for ending in _INFLECTIONS
    )
