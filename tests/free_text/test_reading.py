"""Reading a request into who, when, where and what, from its own words, by vote."""

from __future__ import annotations

from immich_memories.free_text.reading import read_request
from tests.free_text.banked import BankedAsker

REQUEST = "me and friends partying in our 20s"


def test_a_word_belongs_to_a_part_when_two_of_three_answers_put_it_there() -> None:
    # WHY: stands in for the model server; the three answers are banked.
    asker = BankedAsker(
        {"who": ["me and friends"], "when": ["in our 20s"], "where": [], "what": ["partying"]},
        {"who": ["me"], "when": ["in our 20s"], "where": [], "what": ["partying"]},
        {"who": ["friends"], "when": [], "where": [], "what": ["friends partying"]},
    )

    reading = read_request(REQUEST, asker)

    assert reading.who == ("me", "friends")
    assert reading.when == ("in our 20s",)
    assert reading.what == ("partying",)
    assert reading.where == ()


def test_a_word_split_between_where_and_what_is_content_and_a_tie_is_what() -> None:
    # WHY: stands in for the model server; the three answers are banked.
    asker = BankedAsker(
        {"who": [], "when": [], "where": ["beaches"], "what": ["pools"]},
        {"who": [], "when": [], "where": ["pools"], "what": ["beaches"]},
        {"who": [], "when": [], "where": ["pools"], "what": []},
    )

    reading = read_request("beaches and pools", asker)

    assert reading.what == ("beaches",)
    assert reading.where == ("pools",)


def test_a_cut_off_answer_is_asked_again_not_read_as_empty() -> None:
    answer = {"who": [], "when": [], "where": [], "what": ["cat"]}
    # WHY: stands in for the model server; None is an answer cut off mid-output.
    asker = BankedAsker(answer, None, answer, answer)

    reading = read_request("our cat", asker)

    assert reading.what == ("cat",)
    assert len(asker.questions) == 4
    assert all(answer is not None for answer in reading.answers)


def test_the_model_picks_only_the_requests_own_phrases_in_three_field_orders() -> None:
    answer = {"who": [], "when": [], "where": [], "what": ["cat"]}
    # WHY: stands in for the model server; the question it receives is what is checked.
    asker = BankedAsker(answer, answer, answer)

    read_request("Our cat", asker)

    schemas = [schema for _, schema in asker.questions]
    assert schemas[0]["properties"]["what"]["items"]["enum"] == ["our", "cat", "our cat"]
    assert [list(schema["properties"]) for schema in schemas] == [
        ["who", "when", "where", "what"],
        ["what", "where", "when", "who"],
        ["when", "where", "what", "who"],
    ]
