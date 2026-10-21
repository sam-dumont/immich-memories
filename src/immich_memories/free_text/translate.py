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
    Reason,
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
from immich_memories.free_text.pool_questions import lasts_one_day, one_occasion
from immich_memories.free_text.preparation import NeedsPreparationPreview
from immich_memories.free_text.preparation_scope import PlaceFilter, place_filter
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
    prepare_window: Callable[[WhenLink, PlaceFilter | None], _PreparedView] | None = None,
) -> Ask:
    """Translate a request against the library: every decision keeps its reason for the trace.

    In a household run (#2044), `view` already holds only the pictures the asking accounts
    can see, and `face_accounts`/`picture_accounts` carry that same scope into the pool.

    `prepare_window`, when given, is called with the request's own dates, and the test for
    the pictures its place could keep when metadata alone settles that place (#2749: "at
    home" never prepares the pictures taken away), once the subject is known, and only when
    the reading depends on a caption (`_depends_on_captions`): a
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
    when = _one_day_occasion(request, when, subject, lexicon, asker)
    # Linking a place reads no caption (the subject's heads come from the request's words),
    # so it comes first and tells preparation which pictures are worth reading.
    where = link_where(request, reading.where, subject.heads, household, asker)
    facts = link_facts(request, view, lexicon)
    translation = Translation(reading, who, when, where, facts, subject)
    if prepare_window is not None and _depends_on_captions(subject, who):
        place = place_filter(translation, household, lexicon, asker, trips=trips, printed=printed)
        try:
            view, picture_accounts, face_accounts = prepare_window(when, place)
        except NeedsPreparationPreview as preview:
            return Ask(translation, Pool((), (), NEEDS_PREPARATION, preview.why))
        captions = [picture.caption for picture in view.pictures]
        subject = build_subject(reading, household, captions, lexicon, asker)
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


def _one_day_occasion(
    request: str, when: WhenLink, subject: Subject, lexicon: Lexicon, asker: Asker
) -> WhenLink:
    """The request's dates, ended on their first day when they open one occasion of one day.

    "The birth of my son" is dated from the people file with no end: the occasion is that day
    (#2793). Settled before anything reads the dates, so preparation reads the day, the pool
    keeps the day, and the handoff films it as that special day even when no caption names
    the occasion. A start with no end that is many occasions, or one that lasted longer
    ("our honeymoon"), keeps its open window.
    """
    if when.start is None or when.end is not None or not subject.words:
        return when
    one, why = one_occasion(request, subject, lexicon, asker)
    if not one:
        return when
    lasted, how_long = lasts_one_day(request, when.start, asker)
    if not lasted:
        return when
    said = " | ".join(reason.said for reason in when.reasons if reason.said)
    rule = f"one occasion: {why.rule}; {how_long.rule}"
    ended = Reason(said, rule, f"{when.start} to {when.start}")
    return WhenLink(when.start, when.start, (*when.reasons, ended))


def _depends_on_captions(subject: Subject, who: WhoLink) -> bool:
    """Whether any part of the reading needs a caption a prepared picture carries.

    The subject's own words (#2045) and company ("with friends") both read captions
    (#2068 extends this list; keep it the one predicate everything plugs into).
    """
    return bool(subject.words) or who.company is not None
