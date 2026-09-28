"""The pool: the pictures a request can be filmed from, and whether that is enough.

The linked request narrows the library filter by filter: when, who, where, what the library
measures, then caption grammar on the subject. No model looks at a picture here and nothing
ranks them: the pool goes whole to the regular engine, which chooses. Every filter records how
many pictures it kept and why, so the trace and a report show where a request was lost.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from immich_memories.free_text.facts import LibraryFacts
from immich_memories.free_text.grammar import free_tier
from immich_memories.free_text.lexicon import Lexicon
from immich_memories.free_text.library import LibraryPicture, LibraryView
from immich_memories.free_text.linking import Household, Reason, WhenLink, WhereLink, WhoLink
from immich_memories.free_text.reading import Asker, Reading
from immich_memories.free_text.subject import Subject

# Fewer pictures than this make a short film: the engine used about four a year from a pet's pool.
THIN_BELOW = 12

POSSIBLE, THIN, NOT_POSSIBLE = "possible", "thin", "not possible"


@dataclass(frozen=True)
class Translation:
    """The request as read and linked: what the pool is built from."""

    reading: Reading
    who: WhoLink
    when: WhenLink
    where: WhereLink
    facts: LibraryFacts
    subject: Subject


@dataclass(frozen=True)
class Step:
    """One filter of the funnel: how many pictures it kept, and why."""

    name: str
    kept: int
    reason: Reason


@dataclass(frozen=True)
class Pool:
    """The pictures the engine films from, the funnel that found them, and the verdict."""

    pictures: tuple[LibraryPicture, ...]
    funnel: tuple[Step, ...]
    # "possible", "thin" (a short film) or "not possible" (no film).
    verdict: str
    why: str


class _Funnel:
    def __init__(self, pictures: Sequence[LibraryPicture]) -> None:
        self.pictures = list(pictures)
        self.steps: list[Step] = [
            Step("library", len(self.pictures), Reason("", "every dated picture", "the library"))
        ]

    def keep(self, name: str, kept: Sequence[LibraryPicture], reason: Reason) -> None:
        self.pictures = list(kept)
        self.steps.append(Step(name, len(self.pictures), reason))


def build_pool(
    translation: Translation,
    view: LibraryView,
    household: Household,
    lexicon: Lexicon,
    asker: Asker,
) -> Pool:
    """The pictures the linked request can be filmed from, filter by filter, with a verdict.

    A request the library cannot show says so with the filter that emptied it; a pool is never
    padded with pictures that do not mean the ask.
    """
    funnel = _Funnel(view.pictures)
    _when(funnel, translation.when)
    _subject(funnel, translation.subject, lexicon)
    return _verdict(funnel)


def _when(funnel: _Funnel, when: WhenLink) -> None:
    if not (when.start or when.end):
        return
    kept = [
        picture
        for picture in funnel.pictures
        if (when.start is None or picture.taken_at.date() >= when.start)
        and (when.end is None or picture.taken_at.date() <= when.end)
    ]
    said = f"{when.start or 'any time'} to {when.end or 'open'}"
    funnel.keep("when", kept, Reason("", "taken inside the request's dates", said))


def _subject(funnel: _Funnel, subject: Subject, lexicon: Lexicon) -> None:
    phrases = list(dict.fromkeys((*subject.main, *subject.extent)))
    if not phrases:
        return
    kept = free_tier(funnel.pictures, phrases, lexicon)
    rule = "caption grammar: a thing is the caption's subject, a scene counts anywhere"
    if subject.also:
        rule += f"; a photo may also show {', '.join(subject.also)}, which alone does not count"
    funnel.keep(
        "subject", kept, Reason(", ".join(phrases), rule, f"captions about {', '.join(phrases)}")
    )


def _verdict(funnel: _Funnel) -> Pool:
    kept = funnel.pictures
    path = " -> ".join(f"{step.name} {step.kept}" for step in funnel.steps)
    if not kept:
        emptied = next(step for step in funnel.steps if step.kept == 0)
        verdict = NOT_POSSIBLE
        why = (
            f"nothing left after {emptied.name} ({emptied.reason.said or emptied.reason.rule}: "
            f"{emptied.reason.outcome}); searched {path}"
        )
    else:
        verdict = THIN if len(kept) < THIN_BELOW else POSSIBLE
        why = f"{len(kept)} pictures in the pool; searched {path}"
    return Pool(pictures=tuple(kept), funnel=tuple(funnel.steps), verdict=verdict, why=why)
