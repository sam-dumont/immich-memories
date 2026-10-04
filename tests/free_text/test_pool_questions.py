"""The pool's text-only questions: what they offer, never what a picture shows."""

from __future__ import annotations

from typing import Any

from immich_memories.free_text.pool_questions import printed_words
from immich_memories.free_text.subject import Subject
from tests.free_text.banked import BankedAsker


def _picks(*choices: str) -> dict[str, Any]:
    return {"reason": "banked", "choices": list(choices)}


def _offered(asker: BankedAsker) -> set[str]:
    """Every word any of the asked questions offered the model as a candidate."""
    return {
        option
        for _prompt, schema in asker.questions
        for option in schema["properties"]["choices"]["items"]["enum"]
    }


def test_a_year_already_used_as_the_date_is_never_offered_as_printed_text() -> None:
    subject = Subject(heads=("horses",), words=("horses",))
    asker = BankedAsker()

    words, reason = printed_words("the horses in 2024", ("in 2024",), subject, asker)

    assert words == ()
    assert not asker.questions, "nothing left to offer, so the model is never asked"
    assert reason.outcome == "none"


def test_a_french_year_and_subject_are_never_offered_either() -> None:
    subject = Subject(heads=("chevaux",), words=("chevaux",))
    # WHY: stands in for the model server; "les" is left over (an article the English glue
    # list does not know) and every answer says it is not printed on anything.
    asker = BankedAsker(_picks(), _picks(), _picks())

    words, reason = printed_words("les chevaux en 2024", ("en 2024",), subject, asker)

    assert words == ()
    assert _offered(asker).isdisjoint({"chevaux", "2024"})


def test_a_month_name_in_another_locale_is_read_as_the_date_too() -> None:
    subject = Subject(heads=("katzen",), words=("katzen",))
    # WHY: stands in for the model server; "unsere" is left over and voted down each time.
    asker = BankedAsker(_picks(), _picks(), _picks())

    words, reason = printed_words("unsere katzen im juni 2023", ("im juni 2023",), subject, asker)

    assert words == ()
    assert _offered(asker).isdisjoint({"katzen", "juni", "2023"})


def test_an_age_number_is_a_genuine_printed_candidate_not_a_date() -> None:
    # "ses 100 ans" (her 100th): the reading puts the age phrase in `when`, but 100 is not a
    # year, so it stays a candidate (a number on the cake, the balloons, the banner).
    asker = BankedAsker(_picks("100"), _picks("100"), _picks("100"))

    words, reason = printed_words("ses 100 ans", ("100 ans",), Subject(), asker)

    assert "100" in words
    assert "100" in _offered(asker)


def test_a_year_is_dropped_but_another_number_in_the_same_request_is_not() -> None:
    # "les 100 ans de mamie en 2019": 2019 is the request's own date and is dropped; 100 is an
    # age, not a date, and stays offered.
    asker = BankedAsker(_picks("100"), _picks("100"), _picks("100"))

    words, reason = printed_words(
        "les 100 ans de mamie en 2019", ("100 ans", "en 2019"), Subject(), asker
    )

    assert "2019" not in _offered(asker)
    assert "100" in _offered(asker)
    assert "100" in words


def test_a_genuine_quoted_printed_word_still_survives() -> None:
    request = "a sign saying bienvenue"
    # WHY: stands in for the model server; every answer picks the quoted word as printed.
    asker = BankedAsker(_picks("bienvenue"), _picks("bienvenue"), _picks("bienvenue"))

    words, reason = printed_words(request, (), Subject(), asker)

    assert "bienvenue" in words
    assert reason.outcome != "none"
