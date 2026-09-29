"""A request, start to finish: read, linked, its subject found, and its pool built.

The order is the design's: the model reads the words into parts, code links who and when,
the subject comes from the what-spans, and only then is where linked, because a place phrase
counts only by its words beyond the subject's own nouns.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from immich_memories.free_text.facts import TripRules, link_facts
from immich_memories.free_text.homes import homes_over_time
from immich_memories.free_text.lexicon import Lexicon
from immich_memories.free_text.library import LibraryView
from immich_memories.free_text.linking import Household, link_when, link_where, link_who
from immich_memories.free_text.pool import Pool, PrintedText, Translation, build_pool
from immich_memories.free_text.reading import Asker, read_request
from immich_memories.free_text.subject import build_subject


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
) -> Ask:
    """Translate a request against the library: every decision keeps its reason for the trace."""
    reading = read_request(request, asker)
    who = link_who(request, reading.who, household, lexicon, asker)
    when = link_when(request, reading.when, who, household, asker, today=today)
    captions = [picture.caption for picture in view.pictures]
    subject = build_subject(reading, household, captions, lexicon, asker)
    where = link_where(request, reading.where, subject.heads, household, asker)
    facts = link_facts(request, view, lexicon)
    translation = Translation(reading, who, when, where, facts, subject)
    pool = build_pool(translation, view, household, lexicon, asker, trips=trips, printed=printed)
    return Ask(translation, pool)
