"""A typed film's subtitle: what the film is about, in a few words, or nothing (#2522).

A typed film (a period, a person, a birthday, a holiday, a day across the years) is titled
by what it is and when ("Summer 2025"). Under it, the reader may say what the film is about,
written from the period thesis (`polish.period_thesis`) and the title it sits under, in the
film's language. It may answer nothing rather than write filler.

A line is shown only when it passes every check: no date, no list of places, no name the
facts don't back, not the title again, not a generic phrase, not story filler. A line that
fails one is dropped, and the film has no subtitle, as it had before.

Measured on 80 stored cuts with the small reader: 73 lines passed every check (the prompts
it was picked over: 62 and 71), at about 600 characters and 1.2 s a prompt. Opt-in with the
rest of the model-written text (`title_screens.llm_titles`).
"""

from __future__ import annotations

import difflib
import logging
import re
from collections.abc import Callable, Sequence
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from immich_memories.analysis.judgments.strict_json import bounded_model_text, final_json_object
from immich_memories.i18n import babel_locale
from immich_memories.titles.relationship_words import name_words
from immich_memories.titles.title_guards import calendar_words_in, invented_name

if TYPE_CHECKING:
    from immich_memories.config.loader import Config

logger = logging.getLogger(__name__)

SUBTITLE_VERSION = "film-subtitle-v1"
SUBTITLE_MAX_TOKENS = 120
# A few words; an answer longer than this is refused, never cut mid-word on the card.
SUBTITLE_MAX_CHARS = 120

_PROMPT = """A family film is titled "{title}". {version}
Its period: {thesis}

Give it a subtitle of 2 to 6 words in {language}: the one thing the period was about (its
occasion, or what they did), with a first name only if the period names one. Never the title
again, never a date or a place. Only these facts. If the period says
nothing the title does not already say, answer an empty subtitle: a blank line beats filler.
JSON only: {{"subtitle":"..."}}"""

_YEAR = re.compile(r"\b(?:19|20)\d\d\b")
_NUMERIC_DATE = re.compile(r"\b\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?\b|\b(?:1er|\d{1,2}e)\b")
_WORD = re.compile(r"[\w'-]+")
_STOP = frozenset({
    "a", "an", "the", "and", "of", "in", "on", "at", "to", "with", "for", "from", "by", "its",
    "it", "this", "that", "his", "her", "their", "our",
    "le", "la", "les", "l", "un", "une", "des", "du", "de", "d", "et", "à", "au", "aux", "en",
    "dans", "sur", "avec", "pour", "par", "chez", "sa", "son", "ses", "leur", "leurs", "ce",
    "cette", "ces", "qui", "que", "est", "sont", "été", "ou",
})  # fmt: skip
# Phrases that say nothing about any film in particular.
_GENERIC = (
    "spent time",
    "together",
    "the people",
    "the family",
    "various",
    "moments",
    "ensemble",
    "la famille",
    "les gens",
    "divers",
    "passé du temps",
)
# Story words that say nothing, by stem, so plural and inflected forms match too
# ("journées", "sorties"): a line made only of these is filler.
_FILLER_STEMS = (
    "jour", "journ", "sortie", "moment", "souvenir", "maison", "famil", "quotidien", "ordinaire",
    "promenade", "balade", "vie", "temps", "ensemble", "partag", "instant", "activit", "loisir",
    "day", "outing", "home", "family", "time", "together", "life", "everyday", "ordinary",
    "walk", "memor", "simple", "doux", "douce", "beau", "belle", "joie", "bonheur",
    "heureu", "petit", "grand", "plein", "air", "nature", "été", "hiver", "printemps", "automne",
    "saison", "année", "mois", "période",
)  # fmt: skip
# The two spellings are the same line when they are this close.
_SAME_AS_TITLE = 0.75

CHECKS = (
    "no date",
    "no place list",
    "names backed",
    "not the title",
    "not generic",
    "not filler only",
)


class SubtitleJudge(Protocol):
    """The reader, as the film summary asks it: banked by prompt."""

    def ask(
        self,
        stage: str,
        prompt: str,
        max_tokens: int = ...,
        *,
        json_object: bool = ...,
        json_fields: tuple[str, ...] = ...,
    ) -> str: ...


def subtitle_prompt(*, title: str, thesis: str, language: str) -> str:
    """The question that asks a typed film's subtitle from its thesis and its title."""
    return _PROMPT.format(title=title, version=SUBTITLE_VERSION, thesis=thesis, language=language)


def language_name(locale: str) -> str:
    """The film's language as the summary's prompt names it: "French"."""
    return str(babel_locale(locale).english_name or "English")


def read_subtitle(
    judge: SubtitleJudge,
    *,
    title: str,
    thesis: str,
    places: Sequence[str],
    locale: str,
) -> str | None:
    """The reader's subtitle for this film, or None: an empty answer, an unusable one, or
    one that fails a check."""
    prompt = subtitle_prompt(title=title, thesis=thesis, language=language_name(locale))
    raw = judge.ask(
        "film-subtitle",
        prompt,
        max_tokens=SUBTITLE_MAX_TOKENS,
        json_object=True,
        json_fields=("subtitle",),
    )
    answer = (final_json_object(raw) or {}).get("subtitle")
    if not isinstance(answer, str) or len(answer.strip()) > SUBTITLE_MAX_CHARS:
        return None
    subtitle = bounded_model_text(answer, max_chars=SUBTITLE_MAX_CHARS)
    if not subtitle:
        return None
    if failed := failed_checks(subtitle, title=title, thesis=thesis, places=places, locale=locale):
        logger.info("The film's subtitle was not shown: %s", ", ".join(failed))
        return None
    return subtitle


def failed_checks(
    subtitle: str,
    *,
    title: str,
    thesis: str,
    places: Sequence[str],
    locale: str,
) -> tuple[str, ...]:
    """The checks this subtitle fails, in `CHECKS` order; none means it may be shown."""
    lowered = subtitle.lower()
    mine = _content(subtitle, locale)
    passed = {
        "no date": not _has_date(subtitle, locale),
        "no place list": len(_places_named(lowered, places)) < 2,
        "names backed": invented_name(subtitle, "\n".join([thesis, title, *places]), locale)
        is None,
        "not the title": not _repeats(lowered, mine, title, locale),
        "not generic": not any(phrase in lowered for phrase in _GENERIC),
        "not filler only": not (mine and all(w.startswith(_FILLER_STEMS) for w in mine)),
    }
    return tuple(check for check in CHECKS if not passed[check])


def subtitle_reader(
    config: Config, attempt_dir: Path | str | None
) -> Callable[[], SubtitleJudge] | None:
    """How a run makes the reader its subtitle asks: the summary's, banked in the store and
    writing its calls beside the attempt's. None when the run kept no attempt."""
    if attempt_dir is None:
        return None
    from immich_memories.analysis.judgments.text_judge import StructureTextJudge

    return partial(StructureTextJudge, config, Path(attempt_dir))


def _calendar(locale: str) -> frozenset[str]:
    return calendar_words_in(locale) | calendar_words_in("en")


def _has_date(text: str, locale: str) -> bool:
    if _YEAR.search(text) or _NUMERIC_DATE.search(text):
        return True
    calendar = _calendar(locale)
    words = (w.casefold() for w in name_words(text))
    return any(w in calendar or (w.endswith("s") and w[:-1] in calendar) for w in words)


def _content(text: str, locale: str) -> list[str]:
    """The words that say something: no stop words, numbers or dates."""
    return [
        w
        for w in _WORD.findall(text.lower())
        if w.strip("'-") and w not in _STOP and not w.isdigit() and not _has_date(w, locale)
    ]


def _places_named(lowered: str, places: Sequence[str]) -> set[str]:
    return {
        place
        for place in places
        if len(place) > 2 and re.search(rf"(?<![\w-]){re.escape(place.lower())}(?![\w-])", lowered)
    }


def _repeats(lowered: str, mine: list[str], title: str, locale: str) -> bool:
    if mine and set(mine) <= set(_content(title, locale)):
        return True
    return difflib.SequenceMatcher(None, lowered, title.lower()).ratio() >= _SAME_AS_TITLE
