"""The subject: what the request's photos show, by grammar and WordNet first, the model's vote last.

A phrase's subject is its head noun, the last one ("pictures of our cat": cat), one per
coordinated part ("beaches and pools"). Its other nouns only modify it. Words for the picture
itself, for people and a trailing time phrase are never the subject: facts, faces and dates
prove those.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import pairwise

from immich_memories.free_text.facts import PICTURE_WORDS
from immich_memories.free_text.lexicon import Lexicon, Relative
from immich_memories.free_text.linking import FIRST_PERSON, GLUE, Household, Reason, time_cut
from immich_memories.free_text.reading import Asker, Reading, choose, choose_several, words_of

_COORDINATORS = frozenset({"and", "or"})

_MAIN = """Which of these words name what the owner's photos must mainly show, for this request?
A photo that shows only the other words does not belong. Pick one to four. Reason first. Return
JSON."""
_MOST_MAIN = 4
_KIND = (
    """What is the owner's photos' main subject (subject)? Pick one. Reason first. Return JSON."""
)
_PLACE = "a place"
_KINDS = (_PLACE, "an animal", "a thing", "an activity or event")
_PEOPLE_RULE = (
    "a word for people: faces prove people; only a word you wrote or the doer of an activity "
    "you asked for counts"
)
_CAPTIONS_PER_USE = 8000
_QUALITY = """The owner's request puts a quality word before its subject. Does that quality narrow
which ones belong in the film, or would every one the request means have it anyway? Pick one.
Reason first. Return JSON."""
_NARROWS = "it narrows which ones belong"
_QUALITIES = (_NARROWS, "every one the request means has it anyway")
# A quality filters captions only when enough of them say it: "black cat" is written hundreds of
# times, "live concert" hardly ever (a concert caption says "a band on stage").
_QUALITY_CAPTIONS = 3


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
    # A word WordNet does not hold is a noun, as in caption grammar: "app" is newer than 2006.
    nouns = [word for word in words if lexicon.noun_base(word) or _unknown(word, lexicon)]
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
    # With no noun, the last verb names the subject: "partying" is asked for as it is written.
    doing = [word for word in words if lexicon.verb_base(word)]
    return (nouns[-1:] or doing[-1:]), activity


def _is_doing(word: str, lexicon: Lexicon) -> bool:
    return word.endswith("ing") and lexicon.verb_base(word) is not None


def _unknown(word: str, lexicon: Lexicon) -> bool:
    return (
        word.isalpha()
        and not (lexicon.noun_base(word) or lexicon.verb_base(word))
        and not lexicon.is_adjective(word)
    )


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


class _CaptionWords:
    """How many of the library's captions use each word."""

    def __init__(self, captions: Iterable[str | None]) -> None:
        said = [caption.lower() for caption in captions if caption]
        self._counts = Counter(word for caption in said for word in set(words_of(caption)))
        # Scaled to the library: 2 captions of a few thousand, 10 of eighty thousand.
        self._floor = max(2, len(said) // _CAPTIONS_PER_USE)
        self._said = said

    def says(self, quality: str, noun: str) -> bool:
        # Either word order ("closed eyes" is written "eyes closed"), the noun in either number.
        said = re.escape(quality.lower())
        thing = rf"{re.escape(noun.lower())}(?:e?s)?"
        form = re.compile(rf"\b(?:{said} {thing}|{thing} {said})\b")
        seen = 0
        for caption in self._said:
            seen += form.search(caption) is not None
            if seen >= _QUALITY_CAPTIONS:
                return True
        return False

    def uses(self, word: str) -> bool:
        return sum(self._counts[form] for form in (word, f"{word}s", f"{word}es")) >= self._floor


@dataclass(frozen=True)
class Subject:
    """What the request's photos show, each word with the reason it was kept or dropped."""

    heads: tuple[str, ...] = ()
    words: tuple[str, ...] = ()
    # What a photo must mainly show to belong.
    main: tuple[str, ...] = ()
    # Its own kinds and parts (and, for a place, the parts it inherits): the subject too.
    extent: tuple[str, ...] = ()
    # The other candidates: a photo may show them, they cannot make it belong.
    also: tuple[str, ...] = ()
    # The WordNet relatives offered, each with its label ("part of house").
    relatives: Mapping[str, str] = field(default_factory=dict)
    # "a place", "an animal", "a thing" or "an activity or event"; asked only when an inherited
    # part depends on it.
    kind: str | None = None
    # The model's votes per candidate over its three answers; empty when nothing was asked.
    votes: Mapping[str, int] = field(default_factory=dict)
    reasons: tuple[Reason, ...] = ()


def build_subject(
    reading: Reading,
    household: Household,
    captions: Iterable[str | None],
    lexicon: Lexicon,
    asker: Asker,
) -> Subject:
    """The request's subject: its own words by grammar, the main subject by the model's vote.

    Candidates are the request's subject words and the WordNet kinds and parts of their heads
    that the library's captions use; a word for people is offered only when the request says
    it or it names the doer of an asked activity (hiker for hiking). The model picks the main
    subject, three times in three orders, a word two answers pick is kept; none kept, the
    request's own subject words stand. The main subject's own kinds and parts count as the
    subject; a part it only inherits (a wheel is any wheeled vehicle's) counts for a place,
    whose GPS proves which one, and the model says whether the subject is a place.
    """
    found = subject_words(reading, household, lexicon)
    reasons = list(found.reasons)
    allowed = _people_rule(reading, household, lexicon)
    index = _CaptionWords(captions)
    relatives, candidates, labels = _candidates(found, allowed, index, lexicon, reasons)
    main, votes = _vote_main(reading.request, candidates, labels, asker, reasons)
    if not main and (own := [word for word in found.words if allowed(word)]):
        main = own
        reasons.append(
            Reason(
                "", "nothing left of the model's pick", f"your own subject words: {', '.join(own)}"
            )
        )
    main = _qualities(reading.request, main, index, lexicon, asker, reasons)
    extent, kind = _extent(reading.request, main, relatives, candidates, lexicon, asker, reasons)
    return Subject(
        heads=found.heads,
        words=found.words,
        main=tuple(main),
        extent=tuple(extent),
        also=tuple(word for word in candidates if word not in main and word not in extent),
        relatives=labels,
        kind=kind,
        votes=dict(votes),
        reasons=tuple(reasons),
    )


def _candidates(
    found: SubjectWords,
    allowed: Callable[[str], bool],
    index: _CaptionWords,
    lexicon: Lexicon,
    reasons: list[Reason],
) -> tuple[dict[str, Relative], list[str], dict[str, str]]:
    relatives = {
        relative.word: relative
        for head in found.heads
        for relative in lexicon.relatives(head)
        if relative.word not in found.words and index.uses(relative.word)
    }
    offered = list(dict.fromkeys([*found.words, *relatives]))
    if dropped := [word for word in offered if not allowed(word)]:
        reasons.append(Reason(", ".join(dropped), _PEOPLE_RULE, "dropped"))
    candidates = [word for word in offered if allowed(word)]
    labels = {word: relatives[word].label() for word in candidates if word in relatives}
    if labels:
        reasons.append(
            Reason(
                ", ".join(found.heads),
                "WordNet: its own kinds and parts your captions use; an inherited part says whose",
                "; ".join(f"{word} = {label}" for word, label in labels.items()),
            )
        )
    return relatives, candidates, labels


def _people_rule(reading: Reading, household: Household, lexicon: Lexicon) -> Callable[[str], bool]:
    # People are proven by faces, never by a caption's noun ("a woman", "a child" head a quarter
    # of all captions). A word for people stays only when the request says it, or WordNet forms
    # it from a word the request says: never from its words for people.
    people = people_words(reading, household, lexicon)
    said = [word for word in words_of(reading.request) if word not in people]
    formed = set(said).union(*(lexicon.derived_nouns(word) for word in said))

    def allowed(word: str) -> bool:
        return (
            not lexicon.is_human(word)
            or (lexicon.noun_base(word) or word) in formed
            or word in formed
        )

    return allowed


def _vote_main(
    request: str,
    candidates: Sequence[str],
    labels: Mapping[str, str],
    asker: Asker,
    reasons: list[Reason],
) -> tuple[list[str], Counter[str]]:
    if len(candidates) < 2:
        return list(candidates), Counter()
    data: dict[str, object] = {"owner_request": request}
    if labels:
        data["relations"] = dict(labels)
    main, votes = choose_several(asker, _MAIN, data, candidates, most=_MOST_MAIN)
    reasons.append(
        Reason(
            ", ".join(candidates),
            f"the model picked the main subject ({_tally(votes)})",
            ", ".join(main) or "no word two answers agree on",
        )
    )
    return main, votes


def _qualities(
    request: str,
    main: Sequence[str],
    index: _CaptionWords,
    lexicon: Lexicon,
    asker: Asker,
    reasons: list[Reason],
) -> list[str]:
    # A stated quality narrows the subject only when the model says it narrows which ones belong
    # ("black cat"; every concert is live) and the captions say it: both, or it sets nothing.
    tokens = words_of(request)
    kept: list[str] = []
    for word in main:
        phrase = _stated_quality(tokens, word, lexicon)
        if phrase is None:
            kept.append(word)
        elif not index.says(phrase.split()[0], lexicon.noun_base(word.split()[-1]) or word):
            reasons.append(Reason(phrase, "your captions do not say it", word))
            kept.append(word)
        else:
            answer, votes = choose(
                asker,
                _QUALITY,
                {"owner_request": request, "quality": phrase.split()[0], "subject": word},
                list(_QUALITIES),
            )
            kept.append(phrase if answer == _NARROWS else word)
            reasons.append(Reason(phrase, f"the model says {answer} ({_tally(votes)})", kept[-1]))
    return list(dict.fromkeys(kept))


def _stated_quality(tokens: Sequence[str], word: str, lexicon: Lexicon) -> str | None:
    # The adjective written right before the word's noun in the request, as written.
    head = word.split()[-1]
    base = lexicon.noun_base(head) or head
    for before, token in pairwise(tokens):
        if (lexicon.noun_base(token) or token) == base and before not in GLUE:
            return f"{before} {token}" if lexicon.is_adjective(before) else None
    return None


def _extent(
    request: str,
    main: Sequence[str],
    relatives: Mapping[str, Relative],
    candidates: Sequence[str],
    lexicon: Lexicon,
    asker: Asker,
    reasons: list[Reason],
) -> tuple[list[str], str | None]:
    bases = {lexicon.noun_base(word.split()[-1]) or word.split()[-1] for word in main}
    own = [
        relatives[word]
        for word in candidates
        if word in relatives and word not in main and relatives[word].of in bases
    ]
    kind = None
    if any(relative.shared_with for relative in own):
        kind, votes = choose(
            asker, _KIND, {"owner_request": request, "subject": list(main)}, list(_KINDS)
        )
        reasons.append(
            Reason(
                ", ".join(main),
                f"the model said what kind of subject it is ({_tally(votes)}); a part it "
                "only inherits counts for a place",
                kind,
            )
        )
    extent = [relative.word for relative in own if not relative.shared_with or kind == _PLACE]
    if extent:
        reasons.append(
            Reason(
                ", ".join(main), "its own parts and kinds are the subject too", ", ".join(extent)
            )
        )
    return extent, kind


def _tally(votes: Counter[str]) -> str:
    return ", ".join(f"{word} {count}/3" for word, count in votes.most_common()) or "no answer"
