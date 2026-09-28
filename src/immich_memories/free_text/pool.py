"""The pool: the pictures a request can be filmed from, and whether that is enough.

The linked request narrows the library filter by filter: when, who, where, what the library
measures, then caption grammar on the subject. No model looks at a picture here and nothing
ranks them: the pool goes whole to the regular engine, which chooses. Every filter records how
many pictures it kept and why, so the trace and a report show where a request was lost.
"""

from __future__ import annotations

import bisect
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta

from immich_memories.analysis.moment_grouping import EPISODE_WINDOW_MINUTES
from immich_memories.config_models_automation import TripsConfig
from immich_memories.free_text.facts import LibraryFacts, TripRules
from immich_memories.free_text.grammar import free_tier
from immich_memories.free_text.lexicon import Lexicon
from immich_memories.free_text.library import LibraryPicture, LibraryView
from immich_memories.free_text.linking import Household, Reason, WhenLink, WhereLink, WhoLink
from immich_memories.free_text.reading import Asker, Reading, words_of
from immich_memories.free_text.scopes import in_place
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
    *,
    trips: TripRules | None = None,
) -> Pool:
    """The pictures the linked request can be filmed from, filter by filter, with a verdict.

    A request the library cannot show says so with the filter that emptied it; a pool is never
    padded with pictures that do not mean the ask. `trips` are the trip-detection rules
    (the config's defaults when not given).
    """
    funnel = _Funnel(view.pictures)
    _when(funnel, translation.when)
    _present(funnel, translation.who)
    if placed := in_place(
        translation.where, funnel.pictures, household.homes, trips or TripsConfig()
    ):
        funnel.keep("where", *placed)
    _subject(funnel, translation.subject, lexicon)
    _company(funnel, translation.who, lexicon)
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


def _present(funnel: _Funnel, who: WhoLink) -> None:
    # Someone is present when their face is recognised anywhere in the picture's episode: a baby
    # feeding against a chest or a child seen from behind shows no face of its own.
    if not who.present:
        return
    wanted = set(who.present)
    faces = sorted(p.taken_at for p in funnel.pictures if wanted & p.people)
    episode = timedelta(minutes=EPISODE_WINDOW_MINUTES)

    def near_a_face(picture: LibraryPicture) -> bool:
        at = bisect.bisect_left(faces, picture.taken_at - episode)
        return at < len(faces) and faces[at] <= picture.taken_at + episode

    kept = [picture for picture in funnel.pictures if near_a_face(picture)]
    rule = "a recognised face of theirs in the picture's episode (90 minutes)"
    funnel.keep("who", kept, Reason(", ".join(who.present), rule, "they are there"))


def _company(funnel: _Funnel, who: WhoLink, lexicon: Lexicon) -> None:
    # Company is read from captions: "with kids" needs a caption naming children.
    if who.company is None:
        return
    young = who.company == "children"
    fits: dict[str, bool] = {}

    def names_company(word: str) -> bool:
        if word not in fits:
            fits[word] = lexicon.is_human(word) and (not young or lexicon.is_young(word))
        return fits[word]

    kept = [
        picture
        for picture in funnel.pictures
        if any(names_company(word) for word in words_of(picture.caption or ""))
    ]
    rule = f"a caption naming {who.company} (WordNet's people words)"
    funnel.keep("company", kept, Reason(who.company, rule, f"{who.company} in the photos"))


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
            f"nothing left after {emptied.name} ({emptied.reason.rule} -> "
            f"{emptied.reason.outcome}); searched {path}"
        )
    else:
        verdict = THIN if len(kept) < THIN_BELOW else POSSIBLE
        why = f"{len(kept)} pictures in the pool; searched {path}"
    return Pool(pictures=tuple(kept), funnel=tuple(funnel.steps), verdict=verdict, why=why)
