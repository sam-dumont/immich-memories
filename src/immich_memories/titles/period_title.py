"""A period film is titled by its period; its biggest story may only be the subtitle.

A season, a month or a year is named the way the calendar names it ("Summer 2025",
"July 2025", "2025"), in the film's language. A model asked for a title tends to name
the thing that filled the period instead (a trip album, a birthday), which then reads
as a trip film or a party film. So whatever the model wrote, the period leads: a title
that is already the period stands as written, and anything else it said moves down to
the subtitle, where the story belongs.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import replace
from difflib import SequenceMatcher

from immich_memories.titles.title_guards import (
    _CJK_FILLER_SUBSTRINGS,
    _FILLER_WORDS,
    _YEAR_DIGITS,
    _years_named,
)
from immich_memories.titles.title_routing import PERIOD_MEMORY_TYPES
from immich_memories.titles.title_suggestion import TitleSuggestion

logger = logging.getLogger(__name__)

# A year, or a run of years in any of the forms the film locales write one
# ("2024-25", "2024–2025", "2024〜2025"), with the counter CJK puts after it.
_YEARS = re.compile(
    r"(?<!\d)(?:19|20)\d{2}(?:\s*[-–—〜～~/]\s*(?:(?:19|20)\d{2}|\d{2}))?"
    r"(?!\d)[年년]?"
)
# What is left around a story once the period is lifted out of a title.
_EDGES = " \t,;:.·|/-–—()'\"«»"
# Inflection only ("июль"/"июля", "lipiec"/"lipca"): a different word is a different word.
_SAME_WORD_RATIO = 0.72


def _folded(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _words(text: str) -> list[str]:
    """The folded words of `text`, years and CJK filler lifted out first."""
    stripped = _YEARS.sub(" ", text)
    for substring in _CJK_FILLER_SUBSTRINGS:
        stripped = stripped.replace(substring, " ")
    return [w for w in re.split(r"[\W_]+", _folded(stripped)) if w and w not in _FILLER_WORDS]


def _same_word(word: str, period_words: list[str]) -> bool:
    return any(
        word == known or SequenceMatcher(None, word, known).ratio() >= _SAME_WORD_RATIO
        for known in period_words
    )


def names_the_period(title: str, period: str) -> bool:
    """Whether `title` says the period: its year(s), and its season or month words."""
    years = frozenset(int(y) for y in _YEAR_DIGITS.findall(period))
    if not _years_named(title, years):
        return False
    title_words = _words(title)
    folded = _folded(title)
    return all(word in folded or _same_word(word, title_words) for word in _words(period))


def is_only_the_period(title: str, period: str) -> bool:
    """Whether `title` is the period and nothing more ("L'été 2025" for "Été 2025")."""
    period_words = _words(period)
    return names_the_period(title, period) and all(
        _same_word(word, period_words) for word in _words(title)
    )


def _story_in(title: str, period: str) -> str:
    """What `title` says besides the period: the story it named, sentence-cased."""
    period_words = _words(period)
    text = _YEARS.sub(" ", title)

    def keep(match: re.Match[str]) -> str:
        return "" if _same_word(_folded(match.group(0)), period_words) else match.group(0)

    text = re.sub(r"[^\W\d_]+", keep, text)
    story = re.sub(r"\s+", " ", text).strip(_EDGES)
    if not _words(story):
        return ""
    return story[:1].upper() + story[1:]


def leading_with_the_period(
    suggestion: TitleSuggestion | None, memory_type: str, period: str | None
) -> TitleSuggestion | None:
    """The suggestion with the period as its title and any story as its subtitle.

    Rewritten rather than refused: the model's title has already passed the
    invented-name guard, and it is the story the subtitle should carry ("The road
    north" under "Summer 2025"). Refusing would drop that story with the title.
    """
    if suggestion is None or not period or memory_type not in PERIOD_MEMORY_TYPES:
        return suggestion
    if is_only_the_period(suggestion.title, period):
        return suggestion
    story = _story_in(suggestion.title, period)
    logger.info(
        "Title %r does not lead with the period %r; the period leads, the story follows",
        suggestion.title,
        period,
    )
    return replace(suggestion, title=period, subtitle=story or suggestion.subtitle)
