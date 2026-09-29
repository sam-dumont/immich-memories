"""The handoff: what a translated request becomes, a film from its pool, a special day, or none."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from immich_memories.free_text.facts import LibraryFacts
from immich_memories.free_text.handoff import CatalogueEvent, film_for
from immich_memories.free_text.library import LibraryPicture
from immich_memories.free_text.linking import Reason, WhenLink, WhereLink, WhoLink
from immich_memories.free_text.pool import Pool, Step, Translation
from immich_memories.free_text.reading import Reading
from immich_memories.free_text.subject import Subject
from immich_memories.free_text.trace import explain
from immich_memories.free_text.translate import Ask
from tests.free_text.banked import BankedAsker

NOTHING = Reason("", "", "")


def _picture(asset_id: str, day: str = "2020-05-01") -> LibraryPicture:
    return LibraryPicture(asset_id, datetime.fromisoformat(day).replace(tzinfo=UTC), "photo")


def _ask(request: str, pool: Pool, *, when: WhenLink | None = None) -> Ask:
    translation = Translation(
        reading=Reading(request=request),
        who=WhoLink(),
        when=when or WhenLink(),
        where=WhereLink(),
        facts=LibraryFacts(),
        subject=Subject(),
    )
    return Ask(translation, pool)


def _pool(*pictures: LibraryPicture, **fields: Any) -> Pool:
    fields.setdefault("verdict", "possible")
    fields.setdefault("why", f"{len(pictures)} pictures in the pool")
    return Pool(pictures=pictures, funnel=(Step("library", len(pictures), NOTHING),), **fields)


def _no_events(_day: date) -> list[CatalogueEvent]:
    return []


def test_a_pool_is_filmed_whole_with_the_request_as_its_written_subject() -> None:
    asked = _ask("our cat along the years", _pool(_picture("a"), _picture("b")))

    film = film_for(asked, BankedAsker(), events_on=_no_events)

    assert film.route == "pool"
    assert film.asset_ids == ("a", "b")
    assert film.subject == "our cat along the years"


def test_a_request_the_library_cannot_show_makes_no_film_and_says_why() -> None:
    why = "nothing left after subject (caption grammar -> captions about brunch)"
    asked = _ask("brunches at home", _pool(verdict="not possible", why=why))

    film = film_for(asked, BankedAsker(), events_on=_no_events)

    assert film.route == "none"
    assert film.asset_ids == ()
    assert why in film.reason.line()


def test_an_undated_occasion_found_on_one_day_is_filmed_as_that_special_day() -> None:
    day = date(2018, 6, 9)
    pool = _pool(_picture("w1", "2018-06-09"), one_occasion=True, day=day)

    film = film_for(_ask("our wedding", pool), BankedAsker(), events_on=_no_events)

    assert (film.route, film.day, film.event_id) == ("special_day", day, None)
    assert film.asset_ids == ()


def test_the_model_picks_which_catalogued_occasion_of_that_day_was_asked_for() -> None:
    day = date(2018, 6, 9)
    events = [CatalogueEvent("ev-market", "a street market"), CatalogueEvent("ev-w", "a wedding")]
    pool = _pool(_picture("w1", "2018-06-09"), one_occasion=True, day=day)
    picked = {"reason": "banked", "choice": "a wedding"}

    # WHY: stands in for the model server choosing between the day's occasions.
    film = film_for(
        _ask("our wedding", pool), BankedAsker(*[picked] * 3), events_on=lambda _: events
    )

    assert (film.route, film.event_id) == ("special_day", "ev-w")
    assert "a wedding 3/3" in film.reason.line()


def test_a_dated_occasion_the_model_says_lasted_one_day_is_that_special_day() -> None:
    born = date(2021, 3, 4)
    pool = _pool(_picture("b1", "2021-03-04"), one_occasion=True)
    asked = _ask("the birth of our son", pool, when=WhenLink(start=born))
    one_day = {"reason": "banked", "choice": "one day"}

    # WHY: stands in for the model server asking how long the occasion lasted.
    film = film_for(asked, BankedAsker(*[one_day] * 3), events_on=_no_events)

    assert (film.route, film.day) == ("special_day", born)
    assert "one day 3/3" in film.reason.line()


def test_a_dated_occasion_that_lasted_longer_is_filmed_from_its_pool() -> None:
    pool = _pool(_picture("h1", "2019-08-02"), _picture("h2", "2019-08-09"), one_occasion=True)
    asked = _ask("our honeymoon", pool, when=WhenLink(start=date(2019, 8, 1)))
    longer = {"reason": "banked", "choice": "longer than one day"}

    # WHY: stands in for the model server asking how long the occasion lasted.
    film = film_for(asked, BankedAsker(*[longer] * 3), events_on=_no_events)

    assert film.route == "pool"
    assert film.asset_ids == ("h1", "h2")


def test_a_one_day_date_range_needs_no_question() -> None:
    day = date(2021, 3, 4)
    pool = _pool(_picture("b1", "2021-03-04"), one_occasion=True)
    asked = _ask("the birth of our son", pool, when=WhenLink(start=day, end=day))

    film = film_for(asked, BankedAsker(), events_on=_no_events)

    assert (film.route, film.day) == ("special_day", day)


def test_the_trace_ends_on_what_the_engine_is_handed() -> None:
    day = date(2018, 6, 9)
    asked = _ask("our wedding", _pool(_picture("w1", "2018-06-09"), one_occasion=True, day=day))
    film = film_for(asked, BankedAsker(), events_on=_no_events)

    last = explain(asked, film=film).splitlines()[-1]

    assert last.startswith("FILM     the special day 2018-06-09")
