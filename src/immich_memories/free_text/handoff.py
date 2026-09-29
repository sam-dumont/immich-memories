"""The handoff: what a translated request becomes for the regular engine.

A pool goes whole to the engine as the film's only material, with the request as its written
subject, so its pictures stand on that subject (`pool_is_subject`). One occasion of one day is
the special-day product's, which films the day and its occasion. A request the library cannot
show makes no film and says why.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from immich_memories.free_text.linking import Reason
from immich_memories.free_text.pool import NOT_POSSIBLE
from immich_memories.free_text.pool_questions import tally
from immich_memories.free_text.reading import Asker, choose
from immich_memories.free_text.translate import Ask

_WHICH_EVENT = """The owner asked for a film of one occasion (owner_request). The library found these
occasions on that day. Which one is the occasion asked for? Pick one. Reason first. Return JSON."""

_HOW_LONG = """The request asks for a film of one occasion that starts on date_from. How long did that
occasion itself last, by what the request says? Pick one. Reason first. Return JSON."""
_ONE_DAY, _LONGER = "one day", "longer than one day"

Route = Literal["pool", "special_day", "none"]


@dataclass(frozen=True)
class CatalogueEvent:
    """One occasion the special-days catalogue holds on a day."""

    # None for a day catalogued before occasions had ids: the day is the occasion.
    event_id: str | None
    description: str


@dataclass(frozen=True)
class Film:
    """What the engine is handed: the route, what it films, and why."""

    route: Route
    reason: Reason
    # The pool route: the film's whole reach, and the subject it was curated for.
    asset_ids: tuple[str, ...] = ()
    subject: str = ""
    # The special-day route: the day, and the catalogued occasion on it when there is one.
    day: date | None = None
    event_id: str | None = None

    def line(self) -> str:
        """The handoff as the trace prints it."""
        what = {
            "pool": "the engine films the pool as an album whose written subject is your words",
            "special_day": f"the special day {self.day}",
            "none": "no film",
        }[self.route]
        return f"{what}: {self.reason.outcome} ({self.reason.rule})"


def film_for(
    ask: Ask,
    asker: Asker,
    *,
    events_on: Callable[[date], Sequence[CatalogueEvent]],
) -> Film:
    """Decide what the request is filmed as; `events_on` reads the catalogue for a day.

    One single occasion with a day, found by its pictures or dated by the request, is that
    special day; the model picks between the occasions the catalogue holds on it. Otherwise
    a pool the library can show is the film's whole reach, and "not possible" is no film.
    """
    pool = ask.pool
    one_day = _one_day(ask, asker)
    if one_day is not None:
        day, why = one_day
        return _special_day(ask.request, day, why, events_on(day), asker)
    if pool.verdict == NOT_POSSIBLE:
        return Film("none", Reason("", "not possible: no film", pool.why))
    return Film(
        "pool",
        Reason("", "the pool is the film's whole reach", f"{len(pool.pictures)} pictures"),
        asset_ids=tuple(picture.asset_id for picture in pool.pictures),
        subject=ask.request,
    )


def _one_day(ask: Ask, asker: Asker) -> tuple[date, str] | None:
    pool, when = ask.pool, ask.translation.when
    if not pool.one_occasion:
        return None
    if pool.day is not None:
        return pool.day, "one occasion, on the day its pictures show its people together"
    if when.start is None:
        return None
    if when.end == when.start:
        return when.start, "one occasion, dated to one day"
    answer, votes = choose(
        asker,
        _HOW_LONG,
        {"owner_request": ask.request, "date_from": when.start.isoformat()},
        # No majority falls back to the first option: longer keeps the pool.
        [_LONGER, _ONE_DAY],
    )
    if answer != _ONE_DAY:
        return None
    return when.start, f"one occasion; the model says it lasted {_ONE_DAY} ({tally(votes)})"


def _special_day(
    request: str, day: date, why: str, events: Sequence[CatalogueEvent], asker: Asker
) -> Film:
    rule = f"{why}: the special-day product films it"
    if not events:
        return Film("special_day", Reason("", rule, f"{day}, not catalogued"), day=day)
    by_label = {event.description: event for event in events}
    picked, votes = choose(asker, _WHICH_EVENT, {"owner_request": request}, list(by_label))
    event = by_label[picked]
    if len(by_label) > 1:
        rule += f"; the model picked the day's occasion ({tally(votes)})"
    return Film(
        "special_day", Reason("", rule, f"{day}, {picked}"), day=day, event_id=event.event_id
    )
