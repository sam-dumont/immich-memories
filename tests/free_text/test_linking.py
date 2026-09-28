"""Linking a reading to the library by code: people, dates, places, each with its reason."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from immich_memories.free_text.homes import Home
from immich_memories.free_text.lexicon import Lexicon
from immich_memories.free_text.library import LibraryPerson
from immich_memories.free_text.linking import (
    Household,
    WhoLink,
    link_when,
    link_where,
    link_who,
    time_cut,
)
from tests.free_text.banked import BankedAsker

OWNER = LibraryPerson("p-owner", "Ada Example", None, date(1990, 6, 15))
PARTNER = LibraryPerson("p-partner", "Bo Example", "partner", date(1991, 2, 1))
SON = LibraryPerson("p-son", "Cy Example", "son", date(2020, 3, 10))
FRIEND = LibraryPerson("p-friend", "Di Sample", "friend", None)
PEOPLE = {person.person_id: person for person in (OWNER, PARTNER, SON, FRIEND)}
HOUSEHOLD = Household(PEOPLE, "p-owner")
STRANGERS = Household(PEOPLE)


def _unasked() -> BankedAsker:
    # WHY: stands in for the model server; an empty bank fails any question asked.
    return BankedAsker()


def test_i_is_the_owner_for_dates_and_homes_never_a_face(lexicon: Lexicon) -> None:
    who = link_who("the cars I drove", ("i",), HOUSEHOLD, lexicon, _unasked())

    assert who.anchors == ("p-owner",)
    assert who.present == ()
    assert who.company is None
    assert "no face" in who.reasons[0].rule


def test_we_is_the_owner_and_the_partner_by_role(lexicon: Lexicon) -> None:
    wife = LibraryPerson("p-wife", "Eve Example", "wife", None)
    people = {"p-owner": OWNER, "p-wife": wife, "p-son": SON}

    who = link_who("our wedding", (), Household(people, "p-owner"), lexicon, _unasked())

    assert who.anchors == ("p-owner", "p-wife")
    assert who.present == ()


def test_a_role_or_a_name_requires_that_persons_face(lexicon: Lexicon) -> None:
    by_role = link_who("my son at the beach", ("my son",), HOUSEHOLD, lexicon, _unasked())
    by_name = link_who("Di and me", ("di",), HOUSEHOLD, lexicon, _unasked())

    assert by_role.present == ("p-son",)
    assert by_name.present == ("p-friend",)
    assert by_role.anchors == ("p-owner", "p-son")
    assert "faces required" in by_role.reasons[-1].rule


def test_a_plural_word_for_people_asks_for_company(lexicon: Lexicon) -> None:
    friends = link_who("me and friends", ("me", "friends"), HOUSEHOLD, lexicon, _unasked())
    kids = link_who("at the park with kids", ("kids",), STRANGERS, lexicon, _unasked())
    cars = link_who("the cars", ("the cars",), STRANGERS, lexicon, _unasked())

    assert (friends.company, friends.present) == ("people", ())
    assert kids.company == "children"
    assert cars == link_who("", (), STRANGERS, lexicon, _unasked())


def test_a_first_name_two_people_share_is_picked_by_vote(lexicon: Lexicon) -> None:
    cousin = LibraryPerson("p-cousin", "Cy Other", "cousin", None)
    people = {**PEOPLE, "p-cousin": cousin}

    cousin_vote = {"reason": "", "choice": "Cy Other (cousin)"}
    # WHY: stands in for the model server; two of three answers pick the cousin.
    asker = BankedAsker(cousin_vote, {"reason": "", "choice": "Cy Example (son)"}, cousin_vote)

    who = link_who("Cy at the beach", ("cy",), Household(people, "p-owner"), lexicon, asker)

    assert who.present == ("p-cousin",)
    assert "2/3" in who.reasons[-1].rule


TODAY = date(2026, 1, 1)
OWNER_ONLY = WhoLink(anchors=("p-owner",))


def test_an_age_is_read_as_numbers_and_the_calendar_is_code() -> None:
    # WHY: stands in for the model server; one anchor means one question.
    asker = BankedAsker(
        {"reason": "", "is_age": True, "whose_age": "Ada Example", "age_from": 20, "age_to": 29}
    )

    when = link_when(
        "me and friends partying in our 20s",
        ("in our 20s",),
        OWNER_ONLY,
        HOUSEHOLD,
        asker,
        today=TODAY,
    )

    assert (when.start, when.end) == (date(2010, 6, 15), date(2020, 6, 14))
    assert "born 1990-06-15" in when.reasons[0].rule


def test_time_words_that_are_no_age_are_dated_by_the_model_from_the_facts() -> None:
    not_an_age = {
        "reason": "",
        "is_age": False,
        "whose_age": "Ada Example",
        "age_from": 0,
        "age_to": 0,
    }
    # WHY: stands in for the model server; the age gate says no, then the dates are banked.
    asker = BankedAsker(not_an_age, {"date_from": "2016-03-01", "date_to": None})

    when = link_when(
        "our house since we moved in",
        ("since we moved in",),
        OWNER_ONLY,
        HOUSEHOLD,
        asker,
        today=TODAY,
    )

    assert (when.start, when.end) == (date(2016, 3, 1), None)
    dates_question = asker.questions[1][0]
    assert '"today": "2026-01-01"' in dates_question


def test_nothing_said_about_time_asks_nothing_and_is_any_time() -> None:
    when = link_when("our cat", (), OWNER_ONLY, HOUSEHOLD, _unasked(), today=TODAY)

    assert (when.start, when.end) == (None, None)
    assert when.reasons[0].outcome == "any time"


def test_years_written_in_the_request_are_found_by_pattern_and_dated() -> None:
    # WHY: stands in for the model server; an invalid day is read as no bound.
    asker = BankedAsker({"date_from": "2014-01-01", "date_to": "2024-13-45"})

    when = link_when("black cat 2014-2024", (), WhoLink(), HOUSEHOLD, asker, today=TODAY)

    assert (when.start, when.end) == (date(2014, 1, 1), None)
    assert '"years_in_request": ["2014", "2024"]' in asker.questions[0][0]


def test_an_age_stands_when_both_orders_of_two_people_read_it_alike() -> None:
    two = WhoLink(anchors=("p-owner", "p-son"))
    son_at_two = {
        "reason": "",
        "is_age": True,
        "whose_age": "Cy Example",
        "age_from": 2,
        "age_to": 2,
    }
    owner_at_two = {**son_at_two, "whose_age": "Ada Example"}
    # WHY: stands in for the model server; two people give two orders of asking.
    agreed = BankedAsker(son_at_two, son_at_two)
    # WHY: as above; the orders disagree, so the dates question is asked instead.
    split = BankedAsker(son_at_two, owner_at_two, {"date_from": None, "date_to": None})

    when = link_when("my son at two", ("at two",), two, HOUSEHOLD, agreed, today=TODAY)
    unsure = link_when("my son at two", ("at two",), two, HOUSEHOLD, split, today=TODAY)

    assert (when.start, when.end) == (date(2022, 3, 10), date(2023, 3, 9))
    assert (unsure.start, unsure.end) == (None, None)


def test_a_trailing_time_phrase_is_cut_from_the_subject_side(lexicon: Lexicon) -> None:
    assert time_cut("closed eyes along the years", lexicon) == "closed eyes"
    assert time_cut("kids in the park over the years", lexicon) == "kids in the park"
    assert time_cut("cars in the park", lexicon) == "cars in the park"


FIRST_HOME = Home(50.0, 4.0, since=None, until=date(2016, 3, 1))
SECOND_HOME = Home(50.1, 4.1, since=date(2016, 3, 1), until=None)
AT_HOMES = Household(PEOPLE, "p-owner", (FIRST_HOME, SECOND_HOME))


def _picks(scope_words: str) -> dict[str, Any]:
    return {"reason": "", "choice": scope_words}


def _option(schema: Mapping[str, Any], starts: str) -> str:
    return next(o for o in schema["properties"]["choice"]["enum"] if o.startswith(starts))


def test_a_place_phrase_is_one_voted_place() -> None:
    def at_home(schema: Mapping[str, Any]) -> dict[str, Any]:
        return _picks(_option(schema, "at home, wherever"))

    # WHY: stands in for the model server; three votes for the home of the time.
    asker = BankedAsker(at_home, at_home, at_home)

    where = link_where("our cat at home", ("at home",), {"cat"}, AT_HOMES, asker)

    assert (where.scope, where.home) == ("home_at_time", None)
    assert "3/3" in where.reasons[0].rule


def test_a_place_phrase_of_only_the_subjects_nouns_says_nowhere() -> None:
    beaches = link_where(
        "beaches and pools", ("beaches and pools",), {"beaches", "pools"}, AT_HOMES, _unasked()
    )
    park = link_where("at the park with kids", ("at the park",), {"park"}, AT_HOMES, _unasked())
    silent = link_where("our cat", (), {"cat"}, AT_HOMES, _unasked())

    assert beaches.scope == park.scope == silent.scope == "anywhere"
    assert beaches.reasons[0].rule == "nothing beyond the subject's own nouns"
    assert silent.reasons[0].rule == "no place words"


def test_home_and_away_together_are_anywhere() -> None:
    def at_home(schema: Mapping[str, Any]) -> dict[str, Any]:
        return _picks(_option(schema, "at home, wherever"))

    def away(schema: Mapping[str, Any]) -> dict[str, Any]:
        return _picks(_option(schema, "away from home"))

    # WHY: stands in for the model server; the first phrase votes home, the second away.
    asker = BankedAsker(at_home, at_home, at_home, away, away, away)

    where = link_where(
        "brunches at home or outside", ("at home", "outside"), {"brunches"}, AT_HOMES, asker
    )

    assert where.scope == "anywhere"


def test_nested_places_give_the_widest_and_one_home_is_that_home() -> None:
    def second_home(schema: Mapping[str, Any]) -> dict[str, Any]:
        return _picks(_option(schema, "at the home lived in from 2016"))

    def near(schema: Mapping[str, Any]) -> dict[str, Any]:
        return _picks(_option(schema, "near home"))

    # WHY: stands in for the model server; one phrase votes a home, the other its town.
    nested = BankedAsker(second_home, second_home, second_home, near, near, near)
    # WHY: as above; one phrase, three votes for the second home.
    one = BankedAsker(second_home, second_home, second_home)

    widest = link_where("x", ("in the house", "around town"), (), AT_HOMES, nested)
    house = link_where("x", ("in the new house",), (), AT_HOMES, one)

    assert widest.scope == "near_home"
    assert (house.scope, house.home) == ("home", SECOND_HOME)
