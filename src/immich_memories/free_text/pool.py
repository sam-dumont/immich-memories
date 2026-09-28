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
from datetime import date, datetime, timedelta
from typing import Protocol

from immich_memories.analysis.moment_grouping import EPISODE_WINDOW_MINUTES
from immich_memories.config_models_automation import TripsConfig
from immich_memories.free_text.facts import (
    LibraryFacts,
    TripRules,
    farthest_trip,
    first_pictures,
    last_pictures,
    occasion_day,
)
from immich_memories.free_text.grammar import free_tier
from immich_memories.free_text.lexicon import Lexicon
from immich_memories.free_text.library import LibraryPicture, LibraryView
from immich_memories.free_text.linking import Household, Reason, WhenLink, WhereLink, WhoLink
from immich_memories.free_text.pool_questions import (
    left_out,
    one_occasion,
    one_particular_place,
    other_names,
    printed_words,
)
from immich_memories.free_text.reading import Asker, Reading, words_of
from immich_memories.free_text.scopes import in_place
from immich_memories.free_text.subject import Subject

# Fewer pictures than this make a short film: the engine used about four a year from a pet's pool.
THIN_BELOW = 12

# The document head's label for an ordinary photograph; None is a picture nothing labelled.
_PHOTOGRAPH = frozenset({None, "photograph"})

# The scopes around a home, where one particular place must prove it was there by GPS.
_AT_HOMES = frozenset({"home", "home_at_time", "near_home"})

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
    # The request asks for one single occasion: the special-day product films it.
    one_occasion: bool = False
    # The day an undated occasion's pictures show its people together.
    day: date | None = None
    # Why the request is, or is not, one single occasion; None when it was not asked.
    occasion: Reason | None = None
    # The words searched for as printed in the photos (OCR): private, like a place name.
    printed: tuple[str, ...] = ()


class _Funnel:
    def __init__(self, pictures: Sequence[LibraryPicture]) -> None:
        self.pictures = list(pictures)
        # A computed selection (one picture per person, one trip) is the film at any size.
        self.computed = False
        # Pictures whose printed text the request names: evidence for the subject by themselves.
        self.anchors: set[str] = set()
        self.printed: tuple[str, ...] = ()
        self.one_occasion = False
        self.occasion: Reason | None = None
        self.day: date | None = None
        self.steps: list[Step] = [
            Step("library", len(self.pictures), Reason("", "every dated picture", "the library"))
        ]

    def keep(self, name: str, kept: Sequence[LibraryPicture], reason: Reason) -> None:
        self.pictures = list(kept)
        self.steps.append(Step(name, len(self.pictures), reason))


class PrintedText(Protocol):
    """Letters really in the photos: Immich's OCR search."""

    def pictures_reading(self, text: str) -> frozenset[str]:
        """The ids of the pictures whose printed text holds `text`."""
        ...


def build_pool(
    translation: Translation,
    view: LibraryView,
    household: Household,
    lexicon: Lexicon,
    asker: Asker,
    *,
    trips: TripRules | None = None,
    printed: PrintedText | None = None,
) -> Pool:
    """The pictures the linked request can be filmed from, filter by filter, with a verdict.

    A request the library cannot show says so with the filter that emptied it; a pool is never
    padded with pictures that do not mean the ask. `trips` are the trip-detection rules
    (the config's defaults when not given); `printed` searches the letters in the photos,
    and without it no printed word is looked for.
    """
    funnel = _Funnel(view.pictures)
    excluded, left_out_reason = left_out(translation.reading.request, asker)
    _when(funnel, translation.when)
    _present(funnel, translation.who)
    rules = trips or TripsConfig()
    if not (printed and _printed(funnel, translation.reading.request, printed, asker)):
        _where(funnel, translation, household, rules, lexicon, asker)
    _measured(funnel, translation.facts)
    if not _computed(funnel, translation.facts, view, household, rules) and not _occasion(
        funnel, translation, view, lexicon, asker
    ):
        names, names_reason = other_names(
            translation.reading.request, translation.subject, funnel.pictures, lexicon, asker
        )
        notes = (names_reason, left_out_reason)
        _subject(funnel, translation.subject, names, excluded, lexicon, notes)
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
    funnel: _Funnel,
    translation: Translation,
    household: Household,
    trips: TripRules,
    lexicon: Lexicon,
    asker: Asker,
) -> None:
    facts = translation.facts
    if facts.places:
        # Immich's place names say where more precisely than a scope around home.
        kept = [picture for picture in funnel.pictures if facts.placed(picture)]
        named = ", ".join(value for _, value in facts.places)
        funnel.keep("place names", kept, Reason(named, "Immich's place names", named))
        return
    require_gps, why = False, None
    if translation.where.scope in _AT_HOMES and translation.subject.main:
        require_gps, why = one_particular_place(
            translation.reading, translation.subject, lexicon, asker
        )
    placed = in_place(
        translation.where, funnel.pictures, household.homes, trips, require_gps=require_gps
    )
    if placed:
        kept, reason = placed
        if why:
            reason = Reason(reason.said, f"{reason.rule}; {why.rule}", reason.outcome)
        funnel.keep("where", kept, reason)


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


def _occasion(
    funnel: _Funnel, translation: Translation, view: LibraryView, lexicon: Lexicon, asker: Asker
) -> bool:
    # One undated occasion ("our wedding") is the day whose pictures of it show everyone it
    # belongs to on the picture itself; that day is the film, whatever else it shows.
    words = translation.subject.words
    if not words:
        return False
    funnel.one_occasion, reason = one_occasion(
        translation.reading.request, translation.subject, lexicon, asker
    )
    funnel.occasion = reason
    if not funnel.one_occasion or translation.when.start or translation.when.end:
        return False
    found = occasion_day(funnel.pictures, words, translation.who.anchors)
    said = ", ".join(words)
    if found.day is None:
        seen = "; ".join(
            f"{day} ({count} photos, showing {_names(view, people)})"
            for day, count, people in found.found
        )
        outcome = found.reason + (f": found {seen}" if seen else "")
        funnel.keep("occasion", [], Reason(said, reason.rule, outcome))
        return True
    funnel.day = found.day
    kept = [picture for picture in funnel.pictures if picture.taken_at.date() == found.day]
    funnel.keep("occasion", kept, Reason(said, reason.rule, found.reason))
    funnel.computed = True
    return True


def _names(view: LibraryView, people: frozenset[str]) -> str:
    known = sorted(view.people[person].name for person in people if person in view.people)
    return ", ".join(known) or "nobody known"


def _present(funnel: _Funnel, who: WhoLink) -> None:
    # Someone is present when their face is recognised anywhere in the picture's episode: a baby
    # feeding against a chest or a child seen from behind shows no face of its own.
    if not who.present:
        return
    wanted = set(who.present)
    faces = [p.taken_at for p in funnel.pictures if wanted & p.people]
    kept = _in_episodes(funnel.pictures, faces)
    rule = "a recognised face of theirs in the picture's episode (90 minutes)"
    funnel.keep("who", kept, Reason(", ".join(who.present), rule, "they are there"))


def _printed(funnel: _Funnel, request: str, printed: PrintedText, asker: Asker) -> bool:
    # A word printed in a photo (a club's name on a jersey) vouches for the photo's episode: the
    # event decides where, and the subject is then read inside it. A name no picture reads is
    # not found, and the pool says so rather than filming any ride.
    words, reason = printed_words(request, asker)
    if not words:
        return False
    funnel.printed = words
    found = frozenset().union(*(printed.pictures_reading(word) for word in words))
    anchors = [picture for picture in funnel.pictures if picture.asset_id in found]
    funnel.anchors = {picture.asset_id for picture in anchors}
    kept = _in_episodes(funnel.pictures, [picture.taken_at for picture in anchors])
    outcome = f"{len(anchors)} pictures read {', '.join(words)}; their episodes are the scope"
    funnel.keep("printed text", kept, Reason(reason.said, reason.rule, outcome))
    return True


def _in_episodes(
    pictures: Sequence[LibraryPicture], moments: Sequence[datetime]
) -> list[LibraryPicture]:
    times = sorted(moments)
    episode = timedelta(minutes=EPISODE_WINDOW_MINUTES)

    def near(picture: LibraryPicture) -> bool:
        at = bisect.bisect_left(times, picture.taken_at - episode)
        return at < len(times) and times[at] <= picture.taken_at + episode

    return [picture for picture in pictures if near(picture)]


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


def _subject(
    funnel: _Funnel,
    subject: Subject,
    names: Sequence[str],
    excluded: Sequence[str],
    lexicon: Lexicon,
    notes: Sequence[Reason | None],
) -> None:
    # Nothing is both the subject and left out, but the request's own nouns stay: "our cat, not
    # the neighbour's cats" still films a cat.
    own = {_head(word, lexicon) for word in subject.heads}
    gone = {_head(phrase, lexicon) for phrase in excluded} - own
    phrases = [
        phrase
        for phrase in dict.fromkeys((*subject.main, *subject.extent, *names))
        if _head(phrase, lexicon) not in gone
    ]
    if not phrases:
        return
    about = {p.asset_id for p in free_tier(funnel.pictures, phrases, lexicon, excluded)}
    kept = [p for p in funnel.pictures if p.asset_id in about or p.asset_id in funnel.anchors]
    rule = "caption grammar: a thing is the caption's subject, a scene counts anywhere"
    if subject.also:
        rule += f"; a photo may also show {', '.join(subject.also)}, which alone does not count"
    rule += "".join(f"; {note.rule}: {note.outcome}" for note in notes if note)
    funnel.keep(
        "subject", kept, Reason(", ".join(phrases), rule, f"captions about {', '.join(phrases)}")
    )


def _head(phrase: str, lexicon: Lexicon) -> str:
    last = words_of(phrase)[-1:]
    return (lexicon.noun_base(last[0]) or last[0]) if last else ""


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
    return Pool(
        pictures=tuple(kept),
        funnel=tuple(funnel.steps),
        verdict=verdict,
        why=why,
        one_occasion=funnel.one_occasion,
        day=funnel.day,
        occasion=funnel.occasion,
        printed=funnel.printed,
    )
