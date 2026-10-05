"""A request, start to finish: read, linked, its subject found, and its pool built.

The order is the design's: the model reads the words into parts, code links who and when,
the subject comes from the what-spans, and only then is where linked, because a place phrase
counts only by its words beyond the subject's own nouns.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType

from immich_memories.free_text.facts import TripRules, link_facts
from immich_memories.free_text.homes import homes_over_time
from immich_memories.free_text.lexicon import Lexicon
from immich_memories.free_text.library import LibraryView
from immich_memories.free_text.linking import (
    Household,
    WhenLink,
    WhoLink,
    link_when,
    link_where,
    link_who,
)
from immich_memories.free_text.pool import (
    NEEDS_PREPARATION,
    Pool,
    PrintedText,
    Translation,
    build_pool,
)
from immich_memories.free_text.preparation import NeedsPreparationPreview
from immich_memories.free_text.reading import Asker, read_request
from immich_memories.free_text.subject import Subject, build_subject, recover_undated_subject

# What `prepare_window` hands back: the refreshed view, and the account scope read fresh
# from it (#2044) -- empty outside a household run.
_PreparedView = tuple[LibraryView, Mapping[str, str], Mapping[str, str | frozenset[str]]]


@dataclass(frozen=True)
class Ask:
    """A request as read and linked, and the pool it can be filmed from."""

    translation: Translation
    pool: Pool

    @property
    def request(self) -> str:
        """The request as typed."""
        return self.translation.reading.request


def household_of(view: LibraryView, *, home_base: tuple[float, float] | None = None) -> Household:
    """The people file, its owner, and the homes the pictures show (else the configured one)."""
    return Household(view.people, view.owner_id, homes_over_time(view.pictures, home_base))


def translate(
    request: str,
    view: LibraryView,
    household: Household,
    lexicon: Lexicon,
    asker: Asker,
    *,
    today: date,
    trips: TripRules | None = None,
    printed: PrintedText | None = None,
    face_accounts: Mapping[str, str | frozenset[str]] = MappingProxyType({}),
    picture_accounts: Mapping[str, str] = MappingProxyType({}),
    prepare_window: Callable[[WhenLink], _PreparedView] | None = None,
) -> Ask:
    """Translate a request against the library: every decision keeps its reason for the trace.

    In a household run (#2044), `view` already holds only the pictures the asking accounts
    can see, and `face_accounts`/`picture_accounts` carry that same scope into the pool.

    `prepare_window`, when given, is called with the request's own dates once the subject
    is known, and only when the reading depends on a caption (`_depends_on_captions`): a
    person or a computed selection (a trip, someone's first or last picture) reads faces
    and GPS, never a caption, so it never pays to prepare a window (#2045). It returns the
    freshly prepared view and the account scope read fresh from it, both of which replace
    `view`/`face_accounts`/`picture_accounts` for everything that follows: a picture
    preparation just discovered needs its own owner, not the stale, pre-preparation one
    (#2044), and the subject itself is rebuilt from the view's now-current captions, so the
    first request to read an unprepared window gets the same subject a second one would.
    A dry run's `prepare_window` raises `NeedsPreparationPreview` instead of returning: the
    pool is not known either way yet, so none is built, and the request answers
    "needs preparation", never "not possible" (#2045).
    """
    reading = read_request(request, asker)
    who = link_who(request, reading.who, household, lexicon, asker)
    when = link_when(request, reading.when, who, household, asker, today=today)
    if when.start is when.end is None:
        reading = recover_undated_subject(reading, lexicon)
    captions = [picture.caption for picture in view.pictures]
    subject = build_subject(reading, household, captions, lexicon, asker)
    if prepare_window is not None and _depends_on_captions(subject, who):
        try:
            view, picture_accounts, face_accounts = prepare_window(when)
        except NeedsPreparationPreview as preview:
            where = link_where(request, reading.where, subject.heads, household, asker)
            facts = link_facts(request, view, lexicon)
            translation = Translation(reading, who, when, where, facts, subject)
            return Ask(translation, Pool((), (), NEEDS_PREPARATION, preview.why))
        captions = [picture.caption for picture in view.pictures]
        subject = build_subject(reading, household, captions, lexicon, asker)
    where = link_where(request, reading.where, subject.heads, household, asker)
    facts = link_facts(request, view, lexicon)
    translation = Translation(reading, who, when, where, facts, subject)
    pool = build_pool(
        translation,
        view,
        household,
        lexicon,
        asker,
        trips=trips,
        printed=printed,
        face_accounts=face_accounts,
        picture_accounts=picture_accounts,
    )
    return Ask(translation, pool)


def _depends_on_captions(subject: Subject, who: WhoLink) -> bool:
    """Whether any part of the reading needs a caption a prepared picture carries.

    The subject's own words (#2045) and company ("with friends") both read captions
    (#2068 extends this list; keep it the one predicate everything plugs into).
    """
    return bool(subject.words) or who.company is not None
