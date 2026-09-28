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
from immich_memories.free_text.facts import (
    LibraryFacts,
    TripRules,
    farthest_trip,
    first_pictures,
    last_pictures,
)
from immich_memories.free_text.grammar import free_tier
from immich_memories.free_text.lexicon import Lexicon
from immich_memories.free_text.library import LibraryPicture, LibraryView
from immich_memories.free_text.linking import Household, Reason, WhenLink, WhereLink, WhoLink
from immich_memories.free_text.reading import Asker, Reading, words_of
from immich_memories.free_text.scopes import in_place
from immich_memories.free_text.subject import Subject

# Fewer pictures than this make a short film: the engine used about four a year from a pet's pool.
THIN_BELOW = 12

# The document head's label for an ordinary photograph; None is a picture nothing labelled.
_PHOTOGRAPH = frozenset({None, "photograph"})

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
        # A computed selection (one picture per person, one trip) is the film at any size.
        self.computed = False
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
    rules = trips or TripsConfig()
    _where(funnel, translation, household, rules)
    _measured(funnel, translation.facts)
    if not _computed(funnel, translation.facts, view, household, rules):
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


def _where(
    funnel: _Funnel, translation: Translation, household: Household, trips: TripRules
) -> None:
    facts = translation.facts
    if facts.places:
        # Immich's place names say where more precisely than a scope around home.
        kept = [picture for picture in funnel.pictures if facts.placed(picture)]
        named = ", ".join(value for _, value in facts.places)
        funnel.keep("place names", kept, Reason(named, "Immich's place names", named))
        return
    if placed := in_place(translation.where, funnel.pictures, household.homes, trips):
        funnel.keep("where", *placed)


def _measured(funnel: _Funnel, facts: LibraryFacts) -> None:
    if facts.picture_kinds:
        kept = [picture for picture in funnel.pictures if facts.of_kind(picture)]
        kinds = ", ".join(facts.picture_kinds)
        reason = Reason(kinds, "the kind of picture preparation labelled", kinds)
    else:
        # A film is made of photographs unless the request names another kind of picture.
        kept = [p for p in funnel.pictures if p.picture_kind in _PHOTOGRAPH]
        reason = Reason("", "no kind of picture named", "photographs and videos, no screens")
    funnel.keep("kind of picture", kept, reason)
    if facts.sharpness is not None and facts.sharpness_line is not None:
        kept = [picture for picture in funnel.pictures if facts.sharp_enough(picture)]
        rule = f"the engine's sharpness line ({facts.sharpness_line:.1f})"
        funnel.keep("sharpness", kept, Reason(facts.sharpness, rule, f"{facts.sharpness} it"))


def _computed(
    funnel: _Funnel,
    facts: LibraryFacts,
    view: LibraryView,
    household: Household,
    trips: TripRules,
) -> bool:
    # A computed selection is the film: the subject does not narrow it.
    if facts.extreme == "farthest":
        trip = farthest_trip(funnel.pictures, household.homes, trips) if household.homes else None
        if trip is None:
            why = "no trip away from a known home" if household.homes else "no home known"
            funnel.keep("farthest", [], Reason("farthest", why, "nothing to measure from"))
            return True
        kept = [picture for picture in funnel.pictures if picture.asset_id in trip.asset_ids]
        funnel.keep("farthest", kept, Reason("farthest", trip.reason, "that whole trip"))
        funnel.computed = True
        return True
    if not facts.people:
        return False
    people = [view.people[person] for person in facts.people if person in view.people]
    if facts.extreme in {"first", "last"}:
        chosen = (first_pictures if facts.extreme == "first" else last_pictures)(
            funnel.pictures, people
        )
        ids = {picture.asset_id for picture in chosen.values()}
        kept = [picture for picture in funnel.pictures if picture.asset_id in ids]
        rule = f"each person's {facts.extreme} picture, by their recognised face"
        funnel.keep(facts.extreme, kept, Reason(facts.extreme, rule, f"{len(chosen)} people"))
        funnel.computed = True
        return True
    wanted = set(facts.people)
    kept = [picture for picture in funnel.pictures if wanted & picture.people]
    rule = "a recognised face of anyone the request counted"
    funnel.keep("faces", kept, Reason(f"{len(wanted)} people", rule, "any of them"))
    return False


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
        verdict = THIN if len(kept) < THIN_BELOW and not funnel.computed else POSSIBLE
        why = f"{len(kept)} pictures in the pool; searched {path}"
    return Pool(pictures=tuple(kept), funnel=tuple(funnel.steps), verdict=verdict, why=why)
