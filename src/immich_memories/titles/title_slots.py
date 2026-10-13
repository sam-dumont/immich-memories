"""Close the empty slots a model title can leave: a dangling word, an orphan separator.

A reader asked for "<people> in <place> · <year>" with no place to give can write
"Robin and Kit in · 2025": a preposition left hanging before the separator, the place
it promised never written. Each segment between separators loses the function words it
ends on, and a segment left with nothing goes with its separator. Only lowercase words
count, so a person called "An" is never mistaken for the article.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import replace

from immich_memories.titles.title_suggestion import TitleSuggestion

logger = logging.getLogger(__name__)


def _words(spaced: str) -> frozenset[str]:
    return frozenset(spaced.split())


# Prepositions, conjunctions and articles a title segment cannot end on, per film language.
_DANGLING_WORDS: dict[str, frozenset[str]] = {
    "en": _words("in at of on from for with and the a an to by during into"),
    "fr": _words("en à au aux de du des dans chez pour avec et le la les un une sur l' d'"),
    "nl": _words("in op te van met en de het een bij naar tijdens"),
    "de": _words(
        "in im am an auf aus bei mit und von vom zu zum zur der die das ein eine nach für"
    ),
    "es": _words("en a al de del con y e el la los las un una por para durante"),
    "it": _words(
        "in a al allo alla ai agli alle nel nello nella nei negli nelle di del dello della "
        "da dal dalla con e ed il lo la i gli le un una per su sul"
    ),
    "pt": _words("em no na nos nas a ao à aos às de do da dos das com e o os as um uma por para"),
    "pl": _words("w we na z ze do i oraz u od po przy dla o"),
    "sv": _words("i på vid av från med och till en ett för under"),
    "ru": _words("в во на с со и у из от по к для о"),
}
# Languages written without spaces end a segment on a particle glued to the word before it.
_DANGLING_SUFFIXES: dict[str, tuple[str, ...]] = {
    "ja": ("の", "と", "で", "に", "へ", "や"),
    "zh": ("在", "和", "的", "与", "跟", "于"),
    "ko": ("에서", "의", "와", "과", "에", "랑"),
}

# A middle dot, bullet or bar anywhere; a dash only between spaces, so "2013-2026" stays whole;
# a comma, colon or semicolon only before a space; the CJK comma and colon as they come.
_MARK = r"(?:[·•|、：]|(?<=\s)[-–—](?=\s)|[:;,](?=\s))"
_SEPARATOR_RUN = re.compile(rf"((?:\s*{_MARK}\s*)+)")
_MARKS = re.compile(_MARK)


def _language(locale: str) -> str:
    return locale.split("-")[0]


def _written_mark(run: str) -> str:
    """A run of several marks ("Kit, · 2025") keeps the last one, spaced as it is written."""
    marks = _MARKS.findall(run)
    if len(marks) == 1:
        return run
    mark = marks[-1]
    if mark in ",;:":
        return f"{mark} "
    if mark in "、：":
        return mark
    return f" {mark} "


def _trimmed(segment: str, language: str, names: Sequence[str]) -> str:
    """The segment without the function words it ends on; a name it ends on stays."""
    words = _DANGLING_WORDS.get(language, frozenset())
    suffixes = _DANGLING_SUFFIXES.get(language, ())
    text = segment.strip()
    while text and not any(text.endswith(name) for name in names):
        head, _, last = text.rpartition(" ")
        if last in words:  # WHY lowercase only: "An" is a person, "an" an article
            text = head.rstrip()
            continue
        suffix = next((s for s in suffixes if text.endswith(s) and len(text) > len(s)), None)
        if suffix is None:
            break
        text = text[: -len(suffix)].rstrip()
    return text


def close_empty_slots(text: str, locale: str, names: Sequence[str] = ()) -> str:
    """`text` with no segment ending on a dangling word, and no empty segment or orphan mark."""
    parts = _SEPARATOR_RUN.split(text)
    language = _language(locale)
    kept: list[str] = []
    for index in range(0, len(parts), 2):
        segment = _trimmed(parts[index], language, names)
        if not segment:
            continue
        if kept:
            kept.append(_written_mark(parts[index - 1]))
        kept.append(segment)
    return "".join(kept)


def closing_empty_slots(
    suggestion: TitleSuggestion | None, locale: str, person_names: Sequence[str]
) -> TitleSuggestion | None:
    """The suggestion with its empty slots closed; ``None`` when nothing of the title is left."""
    if suggestion is None:
        return None
    title = close_empty_slots(suggestion.title, locale, person_names)
    subtitle = (
        close_empty_slots(suggestion.subtitle, locale, person_names) or None
        if suggestion.subtitle
        else None
    )
    if title != suggestion.title:
        logger.info("Title %r left an empty slot; it reads %r", suggestion.title, title)
    if not title:
        return None
    return replace(suggestion, title=title, subtitle=subtitle)
