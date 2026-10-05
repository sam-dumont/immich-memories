"""Refuse a model title that states a relationship the family record doesn't.

Split out of `title_guards` (#2063 round 4) once that module crossed the
800-line soft limit: this is one cohesive concern -- matching a relationship
word in a title against what the people registry actually records -- while
`title_guards` holds the unrelated guards (invented names, years, places,
elision, contentless titles).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import replace
from typing import TYPE_CHECKING

from immich_memories.titles.relationship_words import (
    FAMILY_GENERIC,
    HOLIDAY_NAME_PHRASES,
    MAKER_POSSESSIVES,
    NOT_A_RELATIONSHIP,
    TYPE_ALIASES,
    UNCONDITIONAL_TYPES,
    RelationWord,
    relationship_words,
)
from immich_memories.titles.title_guards import _name_words
from immich_memories.titles.title_suggestion import TitleSuggestion

if TYPE_CHECKING:
    from immich_memories.db import Store
    from immich_memories.people.context import PersonPromptContext

logger = logging.getLogger(__name__)


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


def _isolated_in_window(window: str, marker: str) -> bool:
    """Whether `marker` sits on its own in `window`, not glued to a longer word either side.

    A single CJK syllable such as Korean "내" ("my") is common enough as
    part of an unrelated word ("내내", "안내") that a loose substring check
    on it alone would misfire; a longer marker ("우리", "私の") is specific
    enough that plain containment is fine.
    """
    idx = window.rfind(marker)
    if idx == -1:
        return False
    before_ch = window[idx - 1] if idx > 0 else ""
    after_idx = idx + len(marker)
    after_ch = window[after_idx] if after_idx < len(window) else ""
    return not _NO_WORD_BOUNDARY_SCRIPT.search(before_ch) and not _NO_WORD_BOUNDARY_SCRIPT.search(
        after_ch
    )


def _matches_cjk_marker(window: str, marker: str) -> bool:
    return _isolated_in_window(window, marker) if len(marker) == 1 else marker in window


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
        return any(_matches_cjk_marker(window, marker) for marker in markers)
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


# A word that only reads as a relation next to a possessive or a name: the
# Swedish verb "far" ("to travel") also spells "father" ("vi far till Rom"
# vs. "hans far"); English "nana" is also a children's cereal/nickname
# brand loose enough that it needs the same anchor ("my nana", "Ida's
# nana") before it is read as a grandparent at all.
_WORDS_NEEDING_NEARBY_CONTEXT: dict[tuple[str, str], frozenset[str]] = {
    ("sv", "far"): frozenset({"vår", "vårt", "hans", "hennes", "sin", "sitt", "min", "mitt"}),
    ("en", "nana"): frozenset({"our", "my", "her", "his"}),
}

# English "gran" also opens the place name "Gran Canaria"; it is never a
# relation word immediately before that second word.
_EN_GRAN_PLACE_FOLLOWERS = frozenset({"canaria"})


def _lacks_nearby_context(
    folded: str, lowered: str, span: tuple[int, int], locale: str, known_names: frozenset[str]
) -> bool:
    markers = _WORDS_NEEDING_NEARBY_CONTEXT.get((locale, folded))
    if markers is None:
        return False
    tokens = [t.strip(".,;:!?'’\"") for t in lowered[: span[0]].split()]
    tokens = [t for t in tokens if t]
    nearby = tokens[-_MAKER_POSSESSIVE_WINDOW:]
    return not any(tok in markers or tok in known_names for tok in nearby)


def _is_gran_canaria(folded: str, lowered: str, span: tuple[int, int], locale: str) -> bool:
    if locale != "en" or folded != "gran":
        return False
    following = lowered[span[1] :].lstrip()
    return following.split(" ", 1)[0].rstrip(".,;:!?'’\"") in _EN_GRAN_PLACE_FOLLOWERS


def _span_is_refused(
    folded: str,
    span: tuple[int, int],
    entry: RelationWord,
    lowered: str,
    holders: dict[str, set[str]],
    locale: str,
    known_names: frozenset[str],
) -> bool:
    if _lacks_nearby_context(folded, lowered, span, locale, known_names):
        return False
    if _is_gran_canaria(folded, lowered, span, locale):
        return False
    return _occurrence_is_refused(span, entry, lowered, holders, locale)


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
            if _span_is_refused(folded, span, entry, lowered, holders, locale, known_names):
                return word
    return None


def _without_holiday_name(text: str, locale: str, holiday: str | None) -> str:
    """`text` with the holiday's own name removed, so only what the model added remains."""
    if not holiday:
        return text
    stripped = text
    for phrase in HOLIDAY_NAME_PHRASES.get(locale, frozenset()):
        stripped = re.sub(re.escape(phrase), " ", stripped, flags=re.IGNORECASE)
    return stripped


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
    subtitle alone only drops the subtitle. A holiday's own name ("Fête des
    mères", "Muttertag") is stripped before scanning: naming the holiday is
    naming the day, not a specific person -- but anything the model adds
    beyond the holiday's own name is still scanned like any other title.
    """
    if suggestion is None:
        return suggestion
    words = relationship_words(locale)
    holders = _recorded_relation_people(person_names, people_store)
    known_names = _name_tokens(person_names)
    scanned_title = _without_holiday_name(suggestion.title, locale, holiday)
    if bad := _unfounded_relationship_word(scanned_title, words, holders, known_names, locale):
        logger.warning(
            "Title %r calls somebody %r, a relation the family record does not back; "
            "the template names this memory instead",
            suggestion.title,
            bad,
        )
        return None
    if suggestion.subtitle and (
        bad := _unfounded_relationship_word(
            _without_holiday_name(suggestion.subtitle, locale, holiday),
            words,
            holders,
            known_names,
            locale,
        )
    ):
        logger.info("Subtitle calls somebody %r, which the family record does not back", bad)
        return replace(suggestion, subtitle=None)
    return suggestion
