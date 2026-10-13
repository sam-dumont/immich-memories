"""A subtitle may use the words the app itself writes in the film's language.

Two French films lost a good subtitle: "Subtitle uses 'puis', which no fact in the film backs"
(the summary's own joining word, the model told the story names in it) and "... 'jours' ..."
(the model wrote the French for the "Days at home" its English facts named). The guard is
there for a quality or a mood nothing backs; a word of the film's own catalogue is neither.
"""

from __future__ import annotations

from immich_memories.titles.title_guards import refusing_unbacked_subtitle
from immich_memories.titles.title_suggestion import TitleSuggestion

_FACTS = "Kit\nStories in the film: Orchardville (major); Pooltown (major)"


def _subtitle(line: str, locale: str = "fr") -> str | None:
    kept = refusing_unbacked_subtitle(
        TitleSuggestion("Kit en 2026", line),
        _FACTS,
        "person_spotlight",
        "2025-08-31",
        "2026-08-30",
        ("Kit",),
        locale,
    )
    assert kept is not None
    return kept.subtitle


def test_the_summarys_joining_word_is_not_invented() -> None:
    assert _subtitle("Orchardville puis Pooltown") == "Orchardville puis Pooltown"


def test_the_films_own_words_for_its_stories_are_not_invented() -> None:
    assert _subtitle("Jours à la maison à Pooltown") == "Jours à la maison à Pooltown"


def test_a_mood_nothing_backs_still_drops_the_subtitle() -> None:
    assert _subtitle("Douce lumière sur Pooltown") is None


def test_another_languages_words_back_nothing() -> None:
    # "puis" is French: in an English film it is a word nothing backs.
    assert _subtitle("Orchardville puis Pooltown", "en") is None


def test_the_films_own_words_keep_their_case_while_names_get_theirs() -> None:
    """A French month's subtitle read "Ordinary Days at home: ...": a story name opening on
    "Days" made the casing restorer capitalise every "days"."""
    from immich_memories.titles.title_guards import restore_fact_casing

    facts = "Jours à la maison, 2–6 septembre (major; at Pooltown, Hometown)"
    fixed = restore_fact_casing(
        TitleSuggestion("Septembre 2026", "Des jours ordinaires à la maison à pooltown"),
        facts,
        "fr",
    )

    assert fixed.subtitle == "Des jours ordinaires à la maison à Pooltown"
