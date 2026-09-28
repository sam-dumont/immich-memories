"""The subject: what the request's photos show, by grammar and WordNet first, the model's vote last.

A phrase's subject is its head noun, the last one ("pictures of our cat": cat), one per
coordinated part ("beaches and pools"). Its other nouns only modify it. Words for the picture
itself, for people and a trailing time phrase are never the subject: facts, faces and dates
prove those.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from immich_memories.free_text.facts import PICTURE_WORDS
from immich_memories.free_text.lexicon import Lexicon
from immich_memories.free_text.linking import FIRST_PERSON, GLUE, Household, Reason, time_cut
from immich_memories.free_text.reading import Reading, words_of

_COORDINATORS = frozenset({"and", "or"})


@dataclass(frozen=True)
class SubjectWords:
    """The request's own subject words, as written."""

    # The head noun of each coordinated part: what `link_where` leaves out of a place phrase.
    heads: tuple[str, ...] = ()
    # The heads and the nouns an asked activity forms ("hiking": hike, hiker).
    words: tuple[str, ...] = ()
    reasons: tuple[Reason, ...] = ()


def subject_words(reading: Reading, household: Household, lexicon: Lexicon) -> SubjectWords:
    """The head noun of each coordinated part of the what-spans, by grammar and WordNet."""
    skipped = GLUE | PICTURE_WORDS | people_words(reading, household, lexicon)
    heads: list[str] = []
    found: list[str] = []
    for span in reading.what:
        for part in _parts(time_cut(span, lexicon)):
            head, activity = _head_of([word for word in part if word not in skipped], lexicon)
            heads += head
            found += head + activity
    found = list(dict.fromkeys(found))
    said = " | ".join(reading.what)
    outcome = f"subject words {', '.join(found)}" if found else "no subject"
    rule = (
        "the head noun of each part, and the nouns an activity forms (WordNet); words for "
        "people or the picture itself are skipped"
    )
    return SubjectWords(
        heads=tuple(dict.fromkeys(heads)),
        words=tuple(found),
        reasons=(Reason(said, rule, outcome),),
    )


def _head_of(words: Sequence[str], lexicon: Lexicon) -> tuple[list[str], list[str]]:
    nouns = [word for word in words if lexicon.noun_base(word)]
    # "bread making": the -ing word names the doing and the noun before it what is photographed;
    # the making itself adds nothing (a maker is no subject).
    doing_of = None
    if len(nouns) > 1 and _is_doing(nouns[-1], lexicon):
        doing_of, nouns = nouns[-1], nouns[:-1]
    activity = [
        noun
        for word in words
        if word != doing_of and _is_doing(word, lexicon)
        for noun in sorted(lexicon.derived_nouns(word) - {word})
    ]
    # With no noun, the last word that is a verb or unknown to WordNet names the subject:
    # "breastfeeding" is asked for even when WordNet has no noun for it.
    doing = [w for w in words if lexicon.verb_base(w) or not _known(w, lexicon)]
    return (nouns[-1:] or doing[-1:]), activity


def _is_doing(word: str, lexicon: Lexicon) -> bool:
    return word.endswith("ing") and lexicon.verb_base(word) is not None


def _known(word: str, lexicon: Lexicon) -> bool:
    return lexicon.noun_base(word) is not None or lexicon.is_adjective(word)


def people_words(reading: Reading, household: Household, lexicon: Lexicon) -> frozenset[str]:
    """Words that mean people, never the subject: faces prove people, not a caption's noun.

    The owner's first-person words, the people file's names anywhere in the request, and the
    who-spans' words for people ("friends"). A who-span's other words stay: the reading also
    puts "the cars" under who, and a car is still the subject.
    """
    names = {word for person in household.people.values() for word in words_of(person.name)}
    who = {
        word.removesuffix("'s").removesuffix("’s")
        for span in reading.who
        for word in words_of(span)
    }
    return frozenset(FIRST_PERSON | names | {word for word in who if lexicon.is_human(word)})


def _parts(phrase: str) -> list[list[str]]:
    parts: list[list[str]] = [[]]
    for word in words_of(phrase):
        if word in _COORDINATORS:
            parts.append([])
        else:
            parts[-1].append(word)
    return [part for part in parts if part]
