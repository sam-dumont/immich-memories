"""Small synthetic requests through the production free-text questions and votes."""

from datetime import date
from functools import partial

from immich_memories.config_models_llm import LLMConfig
from immich_memories.conformance.runtime import Case
from immich_memories.free_text.facts import LibraryFacts
from immich_memories.free_text.handoff import CatalogueEvent, film_for
from immich_memories.free_text.library import LibraryPerson
from immich_memories.free_text.linking import (
    Household,
    WhenLink,
    WhereLink,
    WhoLink,
    link_when,
    link_where,
)
from immich_memories.free_text.pool import Pool, Translation
from immich_memories.free_text.pool_questions import left_out, printed_words
from immich_memories.free_text.reading import Reading, WireAsker, read_request
from immich_memories.free_text.subject import Subject, subject_kind
from immich_memories.free_text.translate import Ask

_COMMON = frozenset({"free_text.reading:WireAsker.ask", "free_text.reading:ask_again_if_cut"})


def kind(llm: LLMConfig) -> str:
    answer, votes = subject_kind("photos of cats", ("cat",), WireAsker(llm))
    assert answer == "an animal" and votes[answer] >= 2, "cats were not identified as animals"
    return "majority identifies cats as animals"


def request_reading(llm: LLMConfig) -> str:
    answer = read_request("cats in 2030", WireAsker(llm))
    assert "cats" in " ".join(answer.what), "request reading dropped the cats"
    assert "2030" in " ".join(answer.when), "request reading dropped the year"
    return "keeps cats as subject and 2030 as time"


def calendar_dates(llm: LLMConfig) -> str:
    answer = link_when(
        "cats in 2030", ("2030",), WhoLink(), Household({}), WireAsker(llm), today=date(2031, 1, 1)
    )
    assert (answer.start, answer.end) == (date(2030, 1, 1), date(2030, 12, 31)), "wrong year bounds"
    return "calendar bounds cover exactly 2030"


def age_range(llm: LLMConfig) -> str:
    owner = LibraryPerson("owner", "Avery Example", "owner", date(2000, 1, 1))
    answer = link_when(
        "me at age five",
        ("age five",),
        WhoLink(anchors=("owner",)),
        Household({"owner": owner}, "owner"),
        WireAsker(llm),
        today=date(2030, 1, 1),
    )
    assert (answer.start, answer.end) == (date(2005, 1, 1), date(2005, 12, 31)), "wrong age bounds"
    return "age five maps to the fixture person's fifth year"


def exclusions(llm: LLMConfig) -> str:
    words, _reason = left_out("cars without toy cars", WireAsker(llm))
    assert any("toy" in word for word in words), "exclusion did not preserve the toy qualifier"
    assert "cars" not in words, "exclusion would remove every car"
    return "excludes toy cars without excluding all cars"


def printed(llm: LLMConfig) -> str:
    words, _reason = printed_words("cyclists with VELO printed on their jerseys", WireAsker(llm))
    assert "velo" in words and "jerseys" not in words, "did not isolate the printed word VELO"
    return "selects VELO for OCR matching"


def place_scope(llm: LLMConfig) -> str:
    answer = link_where(
        "photos from our trips", ("from our trips",), (), Household({}), WireAsker(llm)
    )
    assert answer.scope == "trips", "travel request did not select the trips scope"
    return "travel request selects trips rather than anywhere"


def film_handoff(llm: LLMConfig) -> str:
    day = date(2030, 6, 1)
    translation = Translation(
        Reading("our wedding on June 1, 2030"),
        WhoLink(),
        WhenLink(start=day),
        WhereLink(),
        LibraryFacts(),
        Subject(),
    )
    answer = film_for(
        Ask(translation, Pool((), (), "possible", "fixture", one_occasion=True)),
        WireAsker(llm),
        events_on=lambda _: (
            CatalogueEvent("market", "A visit to a market"),
            CatalogueEvent("wedding", "A wedding ceremony"),
        ),
    )
    assert (answer.route, answer.day, answer.event_id) == ("special_day", day, "wedding"), (
        "wrong occasion handoff"
    )
    return "routes the one-day wedding to its catalogue event"


def free_text_cases(llm: LLMConfig) -> tuple[Case, ...]:
    return (
        Case(
            "free-text film handoff",
            partial(film_handoff, llm),
            _COMMON | {"free_text.handoff:_one_day", "free_text.handoff:_special_day"},
        ),
        Case(
            "free-text place scope",
            partial(place_scope, llm),
            _COMMON | {"free_text.linking:link_where", "free_text.reading:choose"},
        ),
        Case(
            "free-text printed words",
            partial(printed, llm),
            _COMMON
            | {"free_text.pool_questions:printed_words", "free_text.reading:choose_several"},
        ),
        Case(
            "free-text exclusions",
            partial(exclusions, llm),
            _COMMON | {"free_text.pool_questions:left_out", "free_text.reading:choose_several"},
        ),
        Case("free-text age range", partial(age_range, llm), _COMMON | {"free_text.linking:_age"}),
        Case(
            "free-text calendar dates",
            partial(calendar_dates, llm),
            _COMMON | {"free_text.linking:_dates"},
        ),
        Case(
            "free-text request reading",
            partial(request_reading, llm),
            _COMMON | {"free_text.reading:read_request"},
        ),
        Case(
            "free-text subject kind",
            partial(kind, llm),
            _COMMON
            | {
                "free_text.subject:subject_kind",
                "free_text.reading:choose",
            },
        ),
    )
