"""A model title may only state a relationship the family record actually backs.

The #1719 campaign named a best friend as "the son of maman et papa", put
parents into a film they were never in, pluralised a grandchild alone, put a
single year on a multi-year span, and let "L'année 2025" through over the
template's plain "2025". Every case here reproduces one of those failures
with synthetic names, through `generate_title_with_llm` with a fake LLM
boundary -- never a real family name, date or place.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest

from immich_memories.titles.llm_titles import MemoryTitleFacts, generate_title_with_llm
from tests.people_registry_seed import seed_people


def _llm_config() -> Any:
    from immich_memories.config_models_llm import LLMConfig

    return LLMConfig(enabled=True, base_url="http://llm.test/v1", model="some-model")


def _reply(title: str, subtitle: str | None = None) -> str:
    import json

    return json.dumps({"title": title, "subtitle": subtitle, "reason": "because"})


def _generate(
    *,
    raw: str,
    memory_type: str,
    person_names: list[str],
    facts: MemoryTitleFacts,
    start_date: str = "2024-01-01",
    end_date: str = "2024-12-31",
):
    """Run the title pipeline with `query_llm` mocked -- the only external boundary."""
    # WHY: query_llm makes a real network call to the reader; this test only
    # exercises what happens to its answer, never whether the call itself works.
    with patch("immich_memories.titles.llm_titles.query_llm") as mock_query:
        mock_query.return_value = raw
        return asyncio.run(
            generate_title_with_llm(
                memory_type=memory_type,
                locale="fr",
                start_date=start_date,
                end_date=end_date,
                duration_days=1,
                person_names=person_names,
                facts=facts,
                llm_config=_llm_config(),
            )
        )


def test_a_best_friend_is_never_called_a_son_in_the_title():
    """The role "best friend" is recorded; "le fils de maman et papa" is not."""
    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [
                {
                    "ids": ["person-friend"],
                    "name": "Milo Example",
                    "birth_date": "2015-06-01",
                    "confirmed": {"role": "best friend"},
                }
            ],
        }
    )
    raw = _reply("Milo, le fils de maman et papa")

    suggestion = _generate(
        raw=raw,
        memory_type="person_spotlight",
        person_names=["Milo Example"],
        facts=MemoryTitleFacts(people_store=store),
    )

    assert suggestion is None


def test_the_prompt_tells_the_model_milo_is_a_best_friend():
    from immich_memories.titles.llm_titles import build_title_prompt

    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [
                {
                    "ids": ["person-friend"],
                    "name": "Milo Example",
                    "birth_date": "2015-06-01",
                    "confirmed": {"role": "best friend"},
                }
            ],
        }
    )
    prompt = build_title_prompt(
        memory_type="person_spotlight",
        locale="fr",
        start_date="2024-01-01",
        end_date="2024-12-31",
        duration_days=365,
        person_names=["Milo Example"],
        facts=MemoryTitleFacts(people_store=store),
    ).text

    assert "best friend" in prompt


def test_a_sons_spotlight_is_not_called_the_grandchild_of_parents_not_in_the_film():
    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [
                {
                    "ids": ["person-son"],
                    "name": "Timo Example",
                    "birth_date": "2018-03-01",
                    "confirmed": {"role": "son"},
                }
            ],
        }
    )
    raw = _reply("Timo, le petit de maman et papa")

    suggestion = _generate(
        raw=raw,
        memory_type="person_spotlight",
        person_names=["Timo Example"],
        facts=MemoryTitleFacts(people_store=store),
    )

    assert suggestion is None


def test_grandchildren_plural_is_refused_for_a_single_grandchild():
    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [
                {
                    "ids": ["person-gma"],
                    "name": "Rosa Example",
                    "confirmed": {"links": [{"kind": "grandparent-of", "with": "person-kid"}]},
                },
                {
                    "ids": ["person-gpa"],
                    "name": "Theo Example",
                    "confirmed": {"links": [{"kind": "grandparent-of", "with": "person-kid"}]},
                },
                {
                    "ids": ["person-kid"],
                    "name": "Nora Example",
                    "birth_date": "2020-01-01",
                    "confirmed": {
                        "links": [
                            {"kind": "grandchild-of", "with": "person-gma"},
                            {"kind": "grandchild-of", "with": "person-gpa"},
                        ]
                    },
                },
            ],
        }
    )
    raw = _reply("Les petits-enfants de Rosa et Theo")

    suggestion = _generate(
        raw=raw,
        memory_type="multi_person",
        person_names=["Rosa Example", "Theo Example", "Nora Example"],
        facts=MemoryTitleFacts(people_store=store),
    )

    assert suggestion is None


def test_a_recorded_relation_between_the_films_own_people_is_kept():
    """Over several years a person spotlight opens on the name alone, no year

    required, so this isolates the relationship guard: a backed relation word
    must survive untouched.
    """
    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [
                {
                    "ids": ["person-gma"],
                    "name": "Rosa Example",
                    "confirmed": {"links": [{"kind": "grandparent-of", "with": "person-kid"}]},
                },
                {
                    "ids": ["person-kid"],
                    "name": "Nora Example",
                    "birth_date": "2020-01-01",
                    "confirmed": {"links": [{"kind": "grandchild-of", "with": "person-gma"}]},
                },
            ],
        }
    )
    raw = _reply("Nora et sa grand-mère")

    with patch("immich_memories.titles.llm_titles.query_llm") as mock_query:
        mock_query.return_value = raw
        suggestion = asyncio.run(
            generate_title_with_llm(
                memory_type="person_spotlight",
                locale="fr",
                start_date="2020-01-01",
                end_date="2024-12-31",
                duration_days=1826,
                person_names=["Nora Example", "Rosa Example"],
                facts=MemoryTitleFacts(people_store=store),
                llm_config=_llm_config(),
            )
        )

    assert suggestion is not None
    assert suggestion.title == "Nora et sa grand-mère"


@pytest.mark.parametrize(
    ("locale", "title", "person_role"),
    [
        ("en", "Noa, mom and dad's son", "son"),
        ("nl", "Noa, de zoon van mama en papa", "son"),
        ("de", "Noa, der Sohn von Mama und Papa", "son"),
        ("es", "Noa, el hijo de mamá y papá", "son"),
        ("it", "Noa, il figlio di mamma e papà", "son"),
        ("pt-BR", "Noa, o filho da mamãe e do papai", "son"),
        ("pt-PT", "Noa, o filho da mamã e do papá", "son"),
        ("pl", "Noa, syn mamy i taty", "son"),
        ("sv", "Noa, mammas och pappas son", "son"),
        ("ru", "Ноа, сын мамы и папы", "son"),
        ("ja", "ママとパパの息子、ノア", "son"),
        ("ko", "엄마와 아빠의 아들, 노아", "son"),
        ("zh-Hans", "妈妈和爸爸的儿子诺亚", "son"),
    ],
)
def test_a_family_word_with_no_recorded_family_is_refused_in_every_locale(
    locale, title, person_role
):
    """One best-friend-named-as-family case per locale, French already covered above."""
    from immich_memories.titles.title_guards import refusing_unfounded_relationships
    from immich_memories.titles.title_suggestion import TitleSuggestion

    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [
                {
                    "ids": ["person-friend"],
                    "name": "Noa Example",
                    "confirmed": {"role": "best friend"},
                }
            ],
        }
    )

    suggestion = TitleSuggestion(title=title, subtitle=None)
    assert refusing_unfounded_relationships(suggestion, ["Noa Example"], locale, store) is None


def test_a_single_year_title_over_a_multi_year_span_is_refused():
    with patch("immich_memories.titles.llm_titles.query_llm") as mock_query:
        mock_query.return_value = _reply("Yuna et maman en 2024")
        suggestion = asyncio.run(
            generate_title_with_llm(
                memory_type="person_spotlight",
                locale="fr",
                start_date="2024-01-01",
                end_date="2026-12-31",
                duration_days=1000,
                person_names=["Yuna Example"],
                facts=MemoryTitleFacts(),
                llm_config=_llm_config(),
            )
        )

    assert suggestion is None


def test_lannee_2025_with_no_other_content_falls_back_to_the_template():
    with patch("immich_memories.titles.llm_titles.query_llm") as mock_query:
        mock_query.return_value = _reply("L'année 2025")
        suggestion = asyncio.run(
            generate_title_with_llm(
                memory_type="multi_person",
                locale="fr",
                start_date="2025-01-01",
                end_date="2025-12-31",
                duration_days=364,
                person_names=["Yuna Example"],
                facts=MemoryTitleFacts(),
                llm_config=_llm_config(),
            )
        )

    assert suggestion is None


def test_hiver_2018_2019_is_accepted():
    from immich_memories.titles.title_guards import requiring_the_year
    from immich_memories.titles.title_suggestion import TitleSuggestion

    suggestion = TitleSuggestion(title="Hiver 2018-2019", subtitle=None)
    result = requiring_the_year(suggestion, "multi_person", "2018-12-01", "2019-02-28", (), None)
    assert result is suggestion


def test_crete_july_2019_is_accepted():
    from immich_memories.titles.title_guards import requiring_the_place
    from immich_memories.titles.title_suggestion import TitleSuggestion

    suggestion = TitleSuggestion(title="Crète, juillet 2019", subtitle=None)
    result = requiring_the_place(suggestion, "Crete, Greece", "fr")
    assert result is suggestion


def test_de_anne_is_elided_to_d_anne():
    from immich_memories.titles.title_guards import eliding_french
    from immich_memories.titles.title_suggestion import TitleSuggestion

    suggestion = TitleSuggestion(title="Le voyage de Anne", subtitle=None)
    result = eliding_french(suggestion, "fr")

    assert result is not None
    assert result.title == "Le voyage d'Anne"


def test_a_single_person_film_states_its_own_relation_to_the_maker():
    """Item 1: a one-person film must get a relation fact too, not just a pair line."""
    from datetime import date

    from immich_memories.titles.llm_titles import people_title_facts

    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [
                {
                    "ids": ["person-friend"],
                    "name": "Milo Example",
                    "confirmed": {"role": "best friend"},
                }
            ],
        }
    )
    facts = people_title_facts(
        ["Milo Example"], date(2024, 1, 1), date(2024, 12, 31), people_store=store
    )

    assert "relation to the film's maker: best friend" in facts


def test_papa_et_maman_is_refused_even_with_the_relation_recorded():
    """The owner's own verdict: "too much papa et maman" -- a backing record

    does not make the child's-eye narration any less overused, so these words
    are refused outright rather than checked against the family record.
    """
    from immich_memories.titles.title_guards import refusing_unfounded_relationships
    from immich_memories.titles.title_suggestion import TitleSuggestion

    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [
                {
                    "ids": ["person-mom"],
                    "name": "Nina Example",
                    "confirmed": {"role": "mother"},
                },
                {
                    "ids": ["person-dad"],
                    "name": "Theo Example",
                    "confirmed": {"role": "father"},
                },
                {
                    "ids": ["person-kid"],
                    "name": "Elio Example",
                    "birth_date": "2020-01-01",
                    "confirmed": {
                        "links": [
                            {"kind": "child-of", "with": "person-mom"},
                            {"kind": "child-of", "with": "person-dad"},
                        ]
                    },
                },
            ],
        }
    )
    suggestion = TitleSuggestion(title="Papa et maman à la plage", subtitle=None)

    result = refusing_unfounded_relationships(
        suggestion, ["Elio Example", "Nina Example", "Theo Example"], "fr", store
    )

    assert result is None


def test_a_friend_named_by_first_name_is_kept():
    """A civil-register or friend word is still governed by the record, not banned."""
    from immich_memories.titles.title_guards import refusing_unfounded_relationships
    from immich_memories.titles.title_suggestion import TitleSuggestion

    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [
                {
                    "ids": ["person-friend"],
                    "name": "Mika Example",
                    "confirmed": {"role": "friend"},
                }
            ],
        }
    )
    suggestion = TitleSuggestion(title="Avec Mika à Rome", subtitle=None)

    result = refusing_unfounded_relationships(suggestion, ["Mika Example"], "fr", store)

    assert result is suggestion
