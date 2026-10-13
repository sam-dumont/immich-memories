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


@lru_cache(maxsize=16)
def _nouns(locale: str) -> frozenset[str]:
    from immich_memories.i18n import film_texts

    words = set(_TITLE_NOUNS.get(locale, frozenset()))
    for relation in relationship_words(locale):
        if len(folded := name_words(relation)) == 1:
            words.add(folded[0].casefold())
    for key, forms in film_texts(locale).items():
        if not key.startswith("holiday."):
            words.update(w.casefold() for form in forms for w in name_words(_SLOT.sub(" ", form)))
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
