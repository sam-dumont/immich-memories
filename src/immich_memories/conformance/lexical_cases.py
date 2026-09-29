"""Synthetic library questions using the pinned public WordNet corpus."""

from datetime import UTC, date, datetime, timedelta
from functools import partial

from immich_memories.config_models_free_text import FreeTextConfig
from immich_memories.config_models_llm import LLMConfig
from immich_memories.conformance.runtime import Case
from immich_memories.free_text.lexicon import load_wordnet
from immich_memories.free_text.library import LibraryPerson, LibraryPicture, LibraryView
from immich_memories.free_text.linking import Household, link_who
from immich_memories.free_text.pool_questions import one_occasion, one_particular_place, other_names
from immich_memories.free_text.reading import Reading, WireAsker
from immich_memories.free_text.subject import PLACE, Subject, build_subject
from immich_memories.free_text.translate import translate


def qualified_subject(llm: LLMConfig) -> str:
    lexicon = load_wordnet(FreeTextConfig().wordnet_path)
    reading = Reading("black cat and dog", what=("black cat and dog",))
    answer = build_subject(
        reading,
        Household({}),
        ["A black cat is sleeping.", "A dog is running."] * 3,
        lexicon,
        WireAsker(llm),
    )
    assert "black cat" in answer.main and "dog" in answer.main, "qualified subjects were lost"
    return "keeps black cat and dog as requested subjects"


def particular_place(llm: LLMConfig) -> str:
    lexicon = load_wordnet(FreeTextConfig().wordnet_path)
    answer, _ = one_particular_place(
        Reading("the house where I grew up", what=("the house",)),
        Subject(heads=("house",), main=("house",), kind=PLACE),
        lexicon,
        WireAsker(llm),
    )
    assert answer, "request did not identify one particular house"
    return "childhood house requires one particular place"


def single_occasion(llm: LLMConfig) -> str:
    answer, _ = one_occasion(
        "our wedding",
        Subject(heads=("wedding",), main=("wedding",)),
        load_wordnet(FreeTextConfig().wordnet_path),
        WireAsker(llm),
    )
    assert answer, "wedding was not identified as one occasion"
    return "wedding selects one occasion"


def alternate_names(llm: LLMConfig) -> str:
    answer, _ = other_names(
        "cats",
        Subject(heads=("cat",), main=("cat",), also=("kitten",)),
        (),
        load_wordnet(FreeTextConfig().wordnet_path),
        WireAsker(llm),
    )
    assert "kitten" in answer, "young cats were omitted from alternate names"
    return "kitten remains a name for a young cat"


def ambiguous_person(llm: LLMConfig) -> str:
    people = {
        "son": LibraryPerson("son", "Avery Sample", "son", None),
        "cousin": LibraryPerson("cousin", "Avery Example", "cousin", None),
    }
    answer = link_who(
        "my cousin Avery",
        ("Avery",),
        Household(people),
        load_wordnet(FreeTextConfig().wordnet_path),
        WireAsker(llm),
    )
    assert answer.present == ("cousin",), "wrong person with the same first name"
    return "role distinguishes the cousin from the son"


def matching_pool(llm: LLMConfig) -> str:
    pictures = tuple(
        LibraryPicture(
            f"{animal}-{n}",
            datetime(2030, 6, 1, tzinfo=UTC) + timedelta(days=n),
            "photo",
            caption=f"A black {animal} is sleeping.",
        )
        for animal, count in (("cat", 14), ("dog", 5))
        for n in range(count)
    )
    answer = translate(
        "black cats",
        LibraryView(pictures, {}, None),
        Household({}),
        load_wordnet(FreeTextConfig().wordnet_path),
        WireAsker(llm),
        today=date(2031, 1, 1),
    )
    kept = {picture.asset_id for picture in answer.pool.pictures}
    assert kept == {f"cat-{n}" for n in range(14)}, "pool does not match the requested black cats"
    return "all 14 black cats retained; all 5 dogs excluded"


def lexical_cases(llm: LLMConfig) -> tuple[Case, ...]:
    return (
        Case(
            "free-text matching pool",
            partial(matching_pool, llm),
            frozenset({"free_text.reading:read_request"}),
        ),
        Case(
            "free-text ambiguous person",
            partial(ambiguous_person, llm),
            frozenset({"free_text.linking:_which"}),
        ),
        Case(
            "free-text other names",
            partial(alternate_names, llm),
            frozenset({"free_text.pool_questions:other_names"}),
        ),
        Case(
            "free-text one occasion",
            partial(single_occasion, llm),
            frozenset({"free_text.pool_questions:one_occasion"}),
        ),
        Case(
            "free-text particular place",
            partial(particular_place, llm),
            frozenset({"free_text.pool_questions:one_particular_place"}),
        ),
        Case(
            "free-text qualified subject",
            partial(qualified_subject, llm),
            frozenset(
                {
                    "free_text.subject:_vote_main",
                    "free_text.subject:_qualities",
                    "free_text.reading:choose",
                    "free_text.reading:choose_several",
                }
            ),
        ),
    )
