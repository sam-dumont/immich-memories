"""Caption grammar: what a caption is about, read from its words alone (no model, no image).

A caption names its subject first ("A black cat is sleeping on a sofa"). The subject runs to
the first verb or preposition, and its last word is the head: "a car seat" is a seat.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Protocol, TypeVar

from immich_memories.free_text.lexicon import Lexicon

# English grammar, not meaning: the first verb or preposition ends a caption's subject. Present
# tense verbs are listed because a small captioner writes "A child rides a toy car".
_SUBJECT_ENDS = re.compile(
    r"\b(is|are|was|were|sits|sit|sitting|stands|standing|lies|lying|lays|laying|rests|resting|"
    r"with|on|in|at|near|next|inside|under|behind|beside|by|against|holding|holds|filled|"
    r"displays|displayed|shows|showing|parked|driving|riding|walking|covered|surrounded|"
    r"featuring|that|which|while|as|from|into|through|rides|drives|plays|walks|runs|looks|hugs|"
    r"carries|pushes|pulls|eats|drinks|sleeps|jumps|climbs|poses|smiles|waves|hangs|leans|"
    r"grazes|flies|swims|reads|watches|uses|wears|feeds|takes|gazes|peeks|peers|stares|"
    r"reaches|kneels|crouches|cuddles|kisses|touches|points|enjoys|perches|hides|seems|"
    r"appears)\b"
)
_WORD = re.compile(r"[a-z]+")
_SUBJECT_WORD = re.compile(r"[a-z]+(?:'s)?")
_PARTICIPLE = re.compile(r"\b[a-z]+ing\b")
# Particles and adverbs that trail a subject: "a black cat curled up".
_TRAILING = frozenset(
    {
        "up",
        "down",
        "out",
        "away",
        "off",
        "together",
        "alone",
        "around",
        "back",
        "over",
        "outside",
        "inside",
        "nearby",
        "there",
        "here",
    }
)
# Words that hold what the caption is about: "a group of cyclists" is cyclists.
_COLLECTIVES = frozenset(
    {
        "group",
        "pair",
        "couple",
        "herd",
        "flock",
        "crowd",
        "team",
        "bunch",
        "pack",
        "litter",
        "family",
        "row",
        "line",
        "pile",
        "collection",
        "set",
        "handful",
        "stack",
        "trio",
    }
)
# Words for the picture itself: "a screenshot of a fitness app" is the app.
_MEDIUM_WORDS = frozenset(
    {
        "screenshot",
        "screenshots",
        "photo",
        "photos",
        "photograph",
        "picture",
        "pictures",
        "image",
        "images",
        "scan",
        "document",
        "map",
        "poster",
        "print",
        "drawing",
        "painting",
    }
)


# WordNet's lexicographer files for things a photo shows as its subject. Anything else (a
# place, an event, an act, a state) is where people are or what they do.
_THING_FILES = frozenset(
    {
        "noun.artifact",
        "noun.food",
        "noun.animal",
        "noun.plant",
        "noun.person",
        "noun.substance",
    }
)


class Captioned(Protocol):
    """A picture with the caption preparation wrote for it (None when nothing read it)."""

    @property
    def caption(self) -> str | None: ...


_Picture = TypeVar("_Picture", bound=Captioned)


def _stem(word: str) -> str:
    return word[:-1] if word.endswith("s") and len(word) > 3 else word


def _subject_words(caption: str) -> list[str]:
    text = caption.lower()
    end = _SUBJECT_ENDS.search(text)
    span = text[: end.start()] if end else text
    if verb := _PARTICIPLE.search(span):
        span = span[: verb.start()]
    span = f" {span} "
    if " of " in span:
        # The head sits before "of" ("a slice of bread" is a slice) unless that word only holds
        # or pictures what follows.
        left, right = span.split(" of ", 1)
        last = _WORD.findall(left)[-1:]
        span = right if last and last[0] in _COLLECTIVES | _MEDIUM_WORDS else left
    words = _SUBJECT_WORD.findall(span)
    while len(words) > 1 and (words[-1].endswith(("ed", "ly")) or words[-1] in _TRAILING):
        words.pop()
    return words


def _stems(text: str) -> set[str]:
    return {_stem(w) for w in _WORD.findall(text.lower())}


def is_about(caption: str | None, phrases: Iterable[str], excluded: Iterable[str] = ()) -> bool:
    """Whether one of the phrases is the caption's grammatical subject.

    A phrase's last word must be the subject's head and its other words must sit in the
    subject: "black cat" needs both, and "a car seat" is a seat, not a car. A possessive
    keeps its owner: "a car's dashboard" is about the car too. An excluded phrase whose words
    all sit in the subject rules the caption out ("toy cars" and "a red toy car").
    """
    words = _subject_words(caption or "")
    if not words:
        return False
    owners = {_stem(w.removesuffix("'s")) for w in words if w.endswith("'s")}
    head = _stem(words[-1].removesuffix("'s"))
    held = {_stem(w.removesuffix("'s")) for w in words}
    if any((stems := _stems(phrase)) and stems <= held for phrase in excluded):
        return False
    for phrase in phrases:
        wanted = [_stem(w) for w in _WORD.findall(phrase.lower())]
        if wanted and (wanted[-1] == head or wanted[-1] in owners) and set(wanted[:-1]) <= held:
            return True
    return False


def is_thing(phrase: str, lexicon: Lexicon) -> bool:
    """Whether the phrase names a thing (a food, an artifact, an animal, a plant, a person).

    WordNet's file for the first noun sense of the phrase's last word decides. A word WordNet
    does not hold ("app" is newer than its 2006 corpus) counts as a thing.
    """
    words = _WORD.findall(phrase.lower())
    if not words:
        return True
    found = lexicon.noun_file(words[-1])
    return found is None or found in _THING_FILES


def free_tier(
    pictures: Iterable[_Picture],
    subject: Sequence[str],
    lexicon: Lexicon,
    excluded: Sequence[str] = (),
) -> list[_Picture]:
    """The pictures whose caption is about the subject, by grammar alone, in their order.

    A thing must be the caption's grammatical subject ("A black cat is sleeping", never "A man
    holding a cat"). A place, an event, an act or a state is where people are and what they
    do, and captions make the people the subject ("children playing in a park"), so its words
    count anywhere in the caption: every word of the phrase, in either order, unless every
    word of an excluded phrase is there too. No subject words at all (the film is about a
    person, and faces chose the pool) keep every captioned picture. A picture without a
    caption is never in the free tier.
    """
    if not subject:
        return [picture for picture in pictures if picture.caption]
    thing = {phrase: is_thing(phrase, lexicon) for phrase in subject}
    things = [phrase for phrase in subject if thing[phrase]]
    scenes = [_stems(phrase) for phrase in subject if not thing[phrase]]
    ruled_out = [words for phrase in excluded if (words := _stems(phrase))]

    def in_scene(caption: str) -> bool:
        said = _stems(caption)
        return any(words and words <= said for words in scenes) and not any(
            words <= said for words in ruled_out
        )

    return [
        picture
        for picture in pictures
        if picture.caption
        and (is_about(picture.caption, things, excluded) or in_scene(picture.caption))
    ]
