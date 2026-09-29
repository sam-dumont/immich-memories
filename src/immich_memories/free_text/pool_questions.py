"""What the pool asks the model about the request: text only, never a picture.

Each question offers the request's own words or the library's words and is voted three times;
grammar gates each one, so a request that says nothing of the kind asks nothing.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

from immich_memories.free_text.facts import PICTURE_WORDS
from immich_memories.free_text.grammar import Captioned, subject_head
from immich_memories.free_text.lexicon import Lexicon
from immich_memories.free_text.linking import FIRST_PERSON, GLUE, Reason
from immich_memories.free_text.reading import Asker, Reading, choose, choose_several, words_of
from immich_memories.free_text.subject import PLACE, Subject, subject_kind

_LEAVE_OUT = """Which of these phrases from the request name what the owner asks to leave out of the
film? None when the request excludes nothing. Reason first. Return JSON."""
# Only what follows a negation can be left out: asked over the whole request, the model left
# out the subject itself ("garden" out of "our garden").
_NEGATED = re.compile(r"\b(?:not|no|without|except|excluding)\b([^.;!?]*)")
_NEGATED_WORD = re.compile(r"[a-z][a-z'’-]*")
_MOST_LEFT_OUT = 4
_MOST_OFFERED = 40


def left_out(request: str, asker: Asker) -> tuple[tuple[str, ...], Reason | None]:
    """The phrases the request asks to leave out, picked by the model from what follows a
    negation ("no toy cars"); nothing asked when the request negates nothing."""
    grams: list[str] = []
    for span in _NEGATED.findall(request.lower()):
        tokens = _NEGATED_WORD.findall(span)
        grams += [
            " ".join(tokens[i : i + n])
            for n in (1, 2, 3)
            for i in range(len(tokens) - n + 1)
            if not set(tokens[i : i + n]) <= GLUE
        ]
    offered = list(dict.fromkeys(grams))[:_MOST_OFFERED]
    if not offered:
        return (), None
    picked, votes = choose_several(
        asker, _LEAVE_OUT, {"owner_request": request}, offered, most=_MOST_LEFT_OUT
    )
    reason = Reason(
        "; ".join(_NEGATED.findall(request.lower())).strip(),
        f"only what follows a negation; the model picked ({tally(votes)})",
        f"leave out {', '.join(picked)}" if picked else "nothing left out",
    )
    return tuple(picked), reason


_SAME_AS = """Which of these words name the main subject itself too: a young one of it, another name
for it, or a kind of it? Only words that do; none when none does. Reason first. Return JSON."""
# A word the captions put in the subject slot this often is how the library names its subjects.
_SLOT_USES = 3
_MOST_SLOT_WORDS = 40
_MOST_SAME = 6


def other_names(
    request: str,
    subject: Subject,
    pictures: Iterable[Captioned],
    lexicon: Lexicon,
    asker: Asker,
) -> tuple[tuple[str, ...], Reason | None]:
    """Other names the captions give the main subject, with its stated quality carried over.

    WordNet's other names for it count as they are. The words the captions put in the
    subject slot ("A black kitten is playing": kitten) are offered to the model, which picks
    those naming the subject too; a word for people never is (faces prove people).
    """
    if not subject.main:
        return (), None
    taken = {word for phrase in (*subject.main, *subject.extent) for word in words_of(phrase)}
    heads = [words_of(phrase)[-1] for phrase in subject.main if words_of(phrase)]
    same = [name for head in heads for name in lexicon.synonyms(head) if name not in taken]
    offered = _slot_words(subject, pictures, taken | set(same), lexicon)
    votes: Counter[str] = Counter()
    if offered:
        picked, votes = choose_several(
            asker,
            _SAME_AS,
            {"owner_request": request, "main_subject": list(subject.main)},
            offered,
            most=_MOST_SAME,
        )
        same += picked
    if not same:
        return (), None
    quality = _qualities(subject.main, lexicon)
    names = tuple(dict.fromkeys(" ".join([*quality, name]) for name in same))
    rule = "WordNet's other names for it, and the caption subjects the model says name it"
    if votes:
        rule += f" ({tally(votes)})"
    return names, Reason(", ".join(subject.main), rule, ", ".join(names))


def _slot_words(
    subject: Subject, pictures: Iterable[Captioned], taken: set[str], lexicon: Lexicon
) -> list[str]:
    slots = Counter(head for picture in pictures if (head := subject_head(picture.caption)))
    common = [word for word, uses in slots.most_common(_MOST_SLOT_WORDS) if uses >= _SLOT_USES]
    return [
        word
        for word in dict.fromkeys([*common, *subject.also])
        if word not in taken
        and word not in PICTURE_WORDS
        and (lexicon.noun_base(word) or word) not in taken
        and not lexicon.is_human(word)
    ]


def _qualities(main: Iterable[str], lexicon: Lexicon) -> list[str]:
    # The main phrase's adjectives carry over ("black cat" and kitten: "black kitten"); a bare
    # part would make a bare kitten.
    phrase = next((words_of(p) for p in main if len(words_of(p)) > 1), [])
    return [word for word in phrase[:-1] if lexicon.is_adjective(word)]


_ONE = """Does the request follow one particular individual of its main subject (the owner's own,
the same one across the photos) or any of that kind? Pick one. Reason first. Return JSON."""
_ONE_OF_IT, _ANY_OF_IT = "one particular individual", "any of that kind"
_POSSESSIVES = frozenset({"my", "our", "his", "her", "their", "your"})


def one_particular_place(
    reading: Reading, subject: Subject, lexicon: Lexicon, asker: Asker
) -> tuple[bool, Reason]:
    """Whether the subject is one particular place ("our house"), which only GPS can prove.

    The model says what kind of subject it is when the subject did not already ask. For a
    place, grammar decides first: a plural head is any of the kind ("beaches"), a possessive
    before a singular head is one ("our house"); otherwise the model is asked.
    """
    said = ", ".join(subject.main)
    kind, votes = (
        (subject.kind, Counter())
        if subject.kind
        else subject_kind(reading.request, subject.main, asker)
    )
    how = f"the model says it is {kind} ({tally(votes)})" if votes else f"it is {kind}"
    if kind != PLACE:
        return False, Reason(said, how, "a picture without GPS stays")
    one = _one_by_grammar(reading, subject, lexicon)
    if one is None:
        answer, votes = choose(
            asker,
            _ONE,
            {"owner_request": reading.request, "subject": list(subject.main)},
            # No majority falls back to the first option: any of the kind sets no filter.
            [_ANY_OF_IT, _ONE_OF_IT],
        )
        one, how = answer == _ONE_OF_IT, f"{how}; the model says {answer} ({tally(votes)})"
    else:
        how += "; grammar: " + ("a possessive before it" if one else "a plural")
    outcome = "one particular place: a picture must carry GPS" if one else "any of that kind"
    return one, Reason(said, how, outcome)


def _one_by_grammar(reading: Reading, subject: Subject, lexicon: Lexicon) -> bool | None:
    if any((lexicon.noun_base(head) or head) != head for head in subject.heads):
        return False
    for span in reading.what or (reading.request,):
        words = [word.removesuffix("'s").removesuffix("’s") for word in words_of(span)]
        for head in subject.heads:
            if head in words:
                before = words_of(span)[: words.index(head)]
                if any(w in _POSSESSIVES or w.endswith(("'s", "’s")) for w in before):
                    return True
    return None


_PRINTED = """Which words of the request would be written on something in the photos (a club or team
name on a jersey, a brand, a sign)? Only a name the request uses that is likely printed on
things; usually none. Reason first. Return JSON."""
_MOST_PRINTED = 3
_SHORTEST_PRINTED = 3


def printed_words(request: str, asker: Asker) -> tuple[tuple[str, ...], Reason]:
    """The request's words the model says are printed on things in the photos (read by OCR)."""
    offered = [
        word
        for word in dict.fromkeys(words_of(request))
        if len(word) >= _SHORTEST_PRINTED and word not in GLUE | FIRST_PERSON | PICTURE_WORDS
    ]
    if not offered:
        return (), Reason("", "no word to read", "none")
    picked, votes = choose_several(
        asker, _PRINTED, {"owner_request": request}, offered, most=_MOST_PRINTED
    )
    rule = f"the model says these are printed on things ({tally(votes)}); OCR reads them"
    return tuple(picked), Reason(", ".join(picked), rule, ", ".join(picked) or "none")


_OCCASIONS = """Does the request ask for the photos of one single occasion (one day, one event, one
trip), or of many occasions? Pick one. Reason first. Return JSON."""
_ONE_OCCASION, _MANY_OCCASIONS = "one single occasion", "many occasions"


def one_occasion(
    request: str, subject: Subject, lexicon: Lexicon, asker: Asker
) -> tuple[bool, Reason]:
    """Whether the request asks for one single occasion ("our wedding").

    A plural subject is many ("brunches"), asked of no one; otherwise the model votes.
    """
    if any((lexicon.noun_base(head) or head) != head for head in subject.heads):
        return False, Reason(", ".join(subject.heads), "grammar: a plural", _MANY_OCCASIONS)
    answer, votes = choose(
        # No majority falls back to the first option: many occasions sets no filter.
        asker,
        _OCCASIONS,
        {"owner_request": request},
        [_MANY_OCCASIONS, _ONE_OCCASION],
    )
    return answer == _ONE_OCCASION, Reason("", f"the model says ({tally(votes)})", answer)


def tally(votes: Counter[str]) -> str:
    """The votes as the trace prints them."""
    return ", ".join(f"{word} {count}/3" for word, count in votes.most_common()) or "no answer"
