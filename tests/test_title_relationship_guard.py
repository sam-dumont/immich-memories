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
    from immich_memories.titles.relationship_guard import refusing_unfounded_relationships
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
    """A pure year failure: no relationship word in the title at all."""
    with patch("immich_memories.titles.llm_titles.query_llm") as mock_query:
        mock_query.return_value = _reply("Yuna en 2024")
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


def test_a_year_outside_the_spans_own_range_is_refused():
    """ "Yuna, été 2021" on a 2024-2026 film names a year the film never reaches."""
    with patch("immich_memories.titles.llm_titles.query_llm") as mock_query:
        mock_query.return_value = _reply("Yuna, été 2021")
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
    from immich_memories.titles.relationship_guard import refusing_unfounded_relationships
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
    from immich_memories.titles.relationship_guard import refusing_unfounded_relationships
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


def test_meilleur_ami_is_not_misread_as_the_shorter_word_ami_inside_it():
    """Longest-match-first: "meilleur ami" is read whole, not as "ami" too."""
    from immich_memories.titles.relationship_guard import refusing_unfounded_relationships
    from immich_memories.titles.title_suggestion import TitleSuggestion

    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [
                {
                    "ids": ["person-friend"],
                    "name": "Luca Example",
                    "confirmed": {"role": "best friend"},
                }
            ],
        }
    )
    suggestion = TitleSuggestion(title="Luca, leur meilleur ami", subtitle=None)

    result = refusing_unfounded_relationships(suggestion, ["Luca Example"], "fr", store)

    assert result is suggestion


def test_a_friend_with_no_recorded_role_is_still_named_as_a_friend():
    """The prompt says a friend is named as a friend; no record is required."""
    from immich_memories.titles.relationship_guard import refusing_unfounded_relationships
    from immich_memories.titles.title_suggestion import TitleSuggestion

    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [{"ids": ["person-a"], "name": "Sana Example"}],
        }
    )
    suggestion = TitleSuggestion(title="Sana, son amie", subtitle=None)

    result = refusing_unfounded_relationships(suggestion, ["Sana Example"], "fr", store)

    assert result is suggestion


def test_a_gender_neutral_sibling_record_backs_the_word_brother():
    """The stored kind is often generic (sibling-of); the word is gendered."""
    from immich_memories.titles.relationship_guard import refusing_unfounded_relationships
    from immich_memories.titles.title_suggestion import TitleSuggestion

    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [
                {
                    "ids": ["person-a"],
                    "name": "Noe Example",
                    "confirmed": {"links": [{"kind": "sibling-of", "with": "person-b"}]},
                },
                {
                    "ids": ["person-b"],
                    "name": "Ilan Example",
                    "confirmed": {"links": [{"kind": "sibling-of", "with": "person-a"}]},
                },
            ],
        }
    )
    suggestion = TitleSuggestion(title="Noe et son frère", subtitle=None)

    result = refusing_unfounded_relationships(
        suggestion, ["Noe Example", "Ilan Example"], "fr", store
    )

    assert result is suggestion


def test_a_person_literally_named_son_is_not_mistaken_for_the_word_son():
    """A word that is a film person's own first name is never a relation claim."""
    from immich_memories.titles.relationship_guard import refusing_unfounded_relationships
    from immich_memories.titles.title_suggestion import TitleSuggestion

    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [{"ids": ["person-a"], "name": "Son Example"}],
        }
    )
    suggestion = TitleSuggestion(title="Son in the garden", subtitle=None)

    result = refusing_unfounded_relationships(suggestion, ["Son Example"], "en", store)

    assert result is suggestion


def test_a_man_on_the_mountain_stays_a_dutch_title_not_a_spouse_claim():
    """nl "man" is an ordinary noun; the spouse word is now the specific echtgenoot."""
    from immich_memories.titles.relationship_guard import refusing_unfounded_relationships
    from immich_memories.titles.title_suggestion import TitleSuggestion

    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [{"ids": ["person-a"], "name": "Finn Example"}],
        }
    )
    suggestion = TitleSuggestion(title="Een man op de berg", subtitle=None)

    result = refusing_unfounded_relationships(suggestion, ["Finn Example"], "nl", store)

    assert result is suggestion


def test_japanese_grandmother_is_read_whole_not_as_the_word_mother_inside_it():
    """ "祖母" (grandmother) must not be misread as "母" (mother) inside it."""
    from immich_memories.titles.relationship_guard import refusing_unfounded_relationships
    from immich_memories.titles.title_suggestion import TitleSuggestion

    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [
                {
                    "ids": ["person-a"],
                    "name": "Mei Example",
                    "confirmed": {"links": [{"kind": "grandparent-of", "with": "person-b"}]},
                },
                {"ids": ["person-b"], "name": "Bo Example"},
            ],
        }
    )
    suggestion = TitleSuggestion(title="Mei 祖母と Bo", subtitle=None)

    result = refusing_unfounded_relationships(
        suggestion, ["Mei Example", "Bo Example"], "ja", store
    )

    assert result is suggestion


def test_korean_strawberry_is_not_misread_as_the_word_daughter():
    """ "딸기" (strawberry) contains "딸" (daughter) but names no relation."""
    from immich_memories.titles.relationship_guard import refusing_unfounded_relationships
    from immich_memories.titles.title_suggestion import TitleSuggestion

    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [{"ids": ["person-a"], "name": "Yuri Example"}],
        }
    )
    suggestion = TitleSuggestion(title="딸기 피크닉", subtitle=None)

    result = refusing_unfounded_relationships(suggestion, ["Yuri Example"], "ko", store)

    assert result is suggestion


def test_our_daughter_is_refused_as_a_relation_to_the_films_maker():
    """ "Tia, notre fille" states a relationship to the maker, which the prompt forbids."""
    from immich_memories.titles.relationship_guard import refusing_unfounded_relationships
    from immich_memories.titles.title_suggestion import TitleSuggestion

    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [
                {
                    "ids": ["person-a"],
                    "name": "Tia Example",
                    "confirmed": {"role": "daughter"},
                }
            ],
        }
    )
    suggestion = TitleSuggestion(title="Tia, notre fille", subtitle=None)

    result = refusing_unfounded_relationships(suggestion, ["Tia Example"], "fr", store)

    assert result is None


def test_abuela_is_record_backed_not_banned_outright():
    """Item 8: Spanish has no separate child's-eye word for grandmother."""
    from immich_memories.titles.relationship_guard import refusing_unfounded_relationships
    from immich_memories.titles.title_suggestion import TitleSuggestion

    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [
                {
                    "ids": ["person-a"],
                    "name": "Elena Example",
                    "confirmed": {"links": [{"kind": "grandparent-of", "with": "person-b"}]},
                },
                {"ids": ["person-b"], "name": "Leo Example"},
            ],
        }
    )
    suggestion = TitleSuggestion(title="Leo y su abuela Elena", subtitle=None)

    result = refusing_unfounded_relationships(
        suggestion, ["Elena Example", "Leo Example"], "es", store
    )

    assert result is suggestion


def test_le_havre_is_not_elided():
    """h aspiré: "le Havre" keeps its "h", never "l'Havre"."""
    from immich_memories.titles.title_guards import eliding_french
    from immich_memories.titles.title_suggestion import TitleSuggestion

    suggestion = TitleSuggestion(title="De Havre à Honfleur", subtitle=None)
    result = eliding_french(suggestion, "fr")

    assert result is not None
    assert result.title == "De Havre à Honfleur"

    suggestion2 = TitleSuggestion(title="Le weekend à la Haye", subtitle=None)
    result2 = eliding_french(suggestion2, "fr")

    assert result2 is not None
    assert result2.title == "Le weekend à la Haye"


def test_yokohama_is_not_elided():
    """A y-initial name never elides: "de Yokohama", not "d'Yokohama"."""
    from immich_memories.titles.title_guards import eliding_french
    from immich_memories.titles.title_suggestion import TitleSuggestion

    suggestion = TitleSuggestion(title="Le voyage de Yokohama", subtitle=None)
    result = eliding_french(suggestion, "fr")

    assert result is not None
    assert result.title == "Le voyage de Yokohama"


def test_hollande_is_not_elided_but_herault_is():
    """The expanded h aspiré list; Hérault is confirmed h muet, not aspiré."""
    from immich_memories.titles.title_guards import eliding_french
    from immich_memories.titles.title_suggestion import TitleSuggestion

    suggestion = TitleSuggestion(title="De Hollande à Hanovre", subtitle=None)
    result = eliding_french(suggestion, "fr")
    assert result is not None
    assert result.title == "De Hollande à Hanovre"

    suggestion2 = TitleSuggestion(title="Le vent de Hérault", subtitle=None)
    result2 = eliding_french(suggestion2, "fr")
    assert result2 is not None
    assert result2.title == "Le vent d'Hérault"


def test_an_unknown_capitalised_h_name_is_left_unelided():
    """ "When unsure, don't elide" a capitalised H name not on the known list."""
    from immich_memories.titles.title_guards import eliding_french
    from immich_memories.titles.title_suggestion import TitleSuggestion

    suggestion = TitleSuggestion(title="Le jardin de Henri", subtitle=None)
    result = eliding_french(suggestion, "fr")

    assert result is not None
    assert result.title == "Le jardin de Henri"


@pytest.mark.parametrize(
    ("locale", "title"),
    [
        ("it", "Buona festa, nonna Lina"),
        ("pl", "Kai i babcia"),
        ("ru", "С бабушкой у моря"),
        ("ko", "할머니와 함께"),
        ("zh-Hans", "和奶奶在一起"),
        ("ja", "おばあちゃんと一緒に"),
    ],
)
def test_the_standard_grandparent_word_is_record_backed_in_every_locale(locale, title):
    """Round 3: these ARE the standard words in their language, not a nickname."""
    from immich_memories.titles.relationship_guard import refusing_unfounded_relationships
    from immich_memories.titles.title_suggestion import TitleSuggestion

    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [
                {
                    "ids": ["person-gma"],
                    "name": "Lina Example",
                    "confirmed": {"links": [{"kind": "grandparent-of", "with": "person-kid"}]},
                },
                {"ids": ["person-kid"], "name": "Kai Example"},
            ],
        }
    )
    suggestion = TitleSuggestion(title=title, subtitle=None)

    result = refusing_unfounded_relationships(
        suggestion, ["Lina Example", "Kai Example"], locale, store
    )

    assert result is suggestion


def test_a_new_childs_eye_word_is_still_refused_outright():
    """Round 3: "papi" (fr, grandfather) and "grandad" (en) are newly added."""
    from immich_memories.titles.relationship_guard import refusing_unfounded_relationships
    from immich_memories.titles.title_suggestion import TitleSuggestion

    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [
                {
                    "ids": ["person-gpa"],
                    "name": "Theo Example",
                    "confirmed": {"links": [{"kind": "grandparent-of", "with": "person-kid"}]},
                },
                {"ids": ["person-kid"], "name": "Kai Example"},
            ],
        }
    )

    fr_suggestion = TitleSuggestion(title="Kai et papi Theo", subtitle=None)
    assert (
        refusing_unfounded_relationships(
            fr_suggestion, ["Theo Example", "Kai Example"], "fr", store
        )
        is None
    )

    en_suggestion = TitleSuggestion(title="Kai and grandad Theo", subtitle=None)
    assert (
        refusing_unfounded_relationships(
            en_suggestion, ["Theo Example", "Kai Example"], "en", store
        )
        is None
    )


def test_a_son_is_refused_when_the_only_record_is_to_the_films_maker():
    """Round 3: the maker's own relation never backs a word, possessive or not."""
    from immich_memories.titles.relationship_guard import refusing_unfounded_relationships
    from immich_memories.titles.title_suggestion import TitleSuggestion

    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [
                {
                    "ids": ["person-kid"],
                    "name": "Elio Example",
                    "confirmed": {"role": "son"},
                }
            ],
        }
    )
    suggestion = TitleSuggestion(title="Elio, le fils, 2024", subtitle=None)

    result = refusing_unfounded_relationships(suggestion, ["Elio Example"], "fr", store)

    assert result is None


def test_our_little_daughter_is_refused_even_with_a_word_between():
    """Round 3: the maker-possessive check looks a few words back, not just one."""
    from immich_memories.titles.relationship_guard import refusing_unfounded_relationships
    from immich_memories.titles.title_suggestion import TitleSuggestion

    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [
                {"ids": ["person-kid"], "name": "Nina Example", "confirmed": {"role": "daughter"}}
            ],
        }
    )
    suggestion = TitleSuggestion(title="Our little daughter Nina", subtitle=None)

    result = refusing_unfounded_relationships(suggestion, ["Nina Example"], "en", store)

    assert result is None


def test_swedish_far_the_verb_is_not_mistaken_for_father():
    """ "Vi far till Rom" (we travel to Rome): "far" with no possessive nearby."""
    from immich_memories.titles.relationship_guard import refusing_unfounded_relationships
    from immich_memories.titles.title_suggestion import TitleSuggestion

    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [{"ids": ["person-a"], "name": "Alva Example"}],
        }
    )
    suggestion = TitleSuggestion(title="Vi far till Rom", subtitle=None)

    result = refusing_unfounded_relationships(suggestion, ["Alva Example"], "sv", store)

    assert result is suggestion


def test_swedish_hans_far_with_no_record_is_refused():
    """Next to a possessive, "far" does read as "father" and still needs a record."""
    from immich_memories.titles.relationship_guard import refusing_unfounded_relationships
    from immich_memories.titles.title_suggestion import TitleSuggestion

    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [{"ids": ["person-a"], "name": "Alva Example"}],
        }
    )
    suggestion = TitleSuggestion(title="Alva och hans far", subtitle=None)

    result = refusing_unfounded_relationships(suggestion, ["Alva Example"], "sv", store)

    assert result is None


def test_korean_emoticon_is_not_misread_as_the_word_aunt():
    """ "이모티콘" (emoticon) contains "이모" (aunt) but names no relation."""
    from immich_memories.titles.relationship_guard import refusing_unfounded_relationships
    from immich_memories.titles.title_suggestion import TitleSuggestion

    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [{"ids": ["person-a"], "name": "Yuri Example"}],
        }
    )
    suggestion = TitleSuggestion(title="이모티콘 모음", subtitle=None)

    result = refusing_unfounded_relationships(suggestion, ["Yuri Example"], "ko", store)

    assert result is suggestion


def test_mothers_day_names_the_holiday_not_a_person():
    """ "Festa della mamma" is a legitimate holiday name, not a narrated relation."""
    with patch("immich_memories.titles.llm_titles.query_llm") as mock_query:
        mock_query.return_value = _reply("Festa della mamma")
        suggestion = asyncio.run(
            generate_title_with_llm(
                memory_type="holiday",
                locale="it",
                start_date="2025-05-11",
                end_date="2025-05-11",
                duration_days=1,
                person_names=[],
                facts=MemoryTitleFacts(holiday="Mother's Day"),
                llm_config=_llm_config(),
            )
        )

    assert suggestion is not None
    assert suggestion.title == "Festa della mamma"


def test_christmas_with_family_names_no_one_and_is_allowed():
    """ "Noël en famille" with nobody named is a mood, not a relation claim."""
    from immich_memories.titles.relationship_guard import refusing_unfounded_relationships
    from immich_memories.titles.title_suggestion import TitleSuggestion

    suggestion = TitleSuggestion(title="Noël en famille", subtitle=None)

    result = refusing_unfounded_relationships(suggestion, [], "fr", None)

    assert result is suggestion


def test_a_distance_in_the_title_is_not_mistaken_for_a_year():
    """ "1200 km" is a distance, not a year, however year-shaped the digits are."""
    with patch("immich_memories.titles.llm_titles.query_llm") as mock_query:
        mock_query.return_value = _reply("Iceland by car, 2025, 1200 km")
        suggestion = asyncio.run(
            generate_title_with_llm(
                memory_type="trip",
                locale="en",
                start_date="2025-06-01",
                end_date="2025-06-10",
                duration_days=9,
                facts=MemoryTitleFacts(place="Iceland"),
                llm_config=_llm_config(),
            )
        )

    assert suggestion is not None
    assert suggestion.title == "Iceland by car, 2025, 1200 km"


def test_the_wrong_year_check_only_looks_at_the_headline():
    """A subtitle may legitimately carry a day's own date outside the span."""
    from immich_memories.titles.title_guards import refusing_a_wrong_year
    from immich_memories.titles.title_suggestion import TitleSuggestion

    suggestion = TitleSuggestion(title="Yuna grandit", subtitle="Photo du 4 juillet 2021")

    result = refusing_a_wrong_year(suggestion, "2024-01-01", "2026-12-31")

    assert result is suggestion


def test_a_possessive_with_an_accent_is_still_matched():
    """Round 3: the maker-possessive check must not accent-fold "mój"/"vår"."""
    from immich_memories.titles.relationship_guard import refusing_unfounded_relationships
    from immich_memories.titles.title_suggestion import TitleSuggestion

    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [{"ids": ["person-a"], "name": "Ola Example", "confirmed": {"role": "son"}}],
        }
    )
    suggestion = TitleSuggestion(title="Mój syn Ola", subtitle=None)

    result = refusing_unfounded_relationships(suggestion, ["Ola Example"], "pl", store)

    assert result is None


def test_notre_annee_with_an_accent_is_still_filler():
    """Round 3: the filler check must not stop matching an accented word."""
    with patch("immich_memories.titles.llm_titles.query_llm") as mock_query:
        mock_query.return_value = _reply("Notre année 2025")
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


def test_voyage_en_images_with_no_place_falls_back_to_the_template():
    """The album-copy shape "<x> en images" names nothing on its own."""
    with patch("immich_memories.titles.llm_titles.query_llm") as mock_query:
        mock_query.return_value = _reply("Notre voyage en images")
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


@pytest.mark.parametrize(
    ("locale", "title", "holiday"),
    [
        ("fr", "Fête des mères avec maman", "Mother's Day"),
        ("en", "Mother's Day with mommy", "Mother's Day"),
        ("fr", "Noël chez papy et mamie", "Christmas"),
    ],
)
def test_a_holiday_title_still_refuses_an_added_perspective_word(locale, title, holiday):
    """Round 4 BLOCKER: the holiday's own name is stripped, not the whole title."""
    with patch("immich_memories.titles.llm_titles.query_llm") as mock_query:
        mock_query.return_value = _reply(title)
        suggestion = asyncio.run(
            generate_title_with_llm(
                memory_type="holiday",
                locale=locale,
                start_date="2025-05-11",
                end_date="2025-05-11",
                duration_days=1,
                person_names=[],
                facts=MemoryTitleFacts(holiday=holiday),
                llm_config=_llm_config(),
            )
        )

    assert suggestion is None


def test_album_copy_shape_falls_back_even_with_a_place_on_it():
    """Round 4: the album-copy shape is filler even with a real place added."""
    with patch("immich_memories.titles.llm_titles.query_llm") as mock_query:
        mock_query.return_value = _reply("Notre voyage en images - Paris")
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


def test_gran_canaria_is_a_place_not_a_grandparent():
    from immich_memories.titles.relationship_guard import refusing_unfounded_relationships
    from immich_memories.titles.title_suggestion import TitleSuggestion

    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [{"ids": ["person-a"], "name": "Mia Example"}],
        }
    )
    suggestion = TitleSuggestion(title="Mia in Gran Canaria", subtitle=None)

    result = refusing_unfounded_relationships(suggestion, ["Mia Example"], "en", store)

    assert result is suggestion


def test_nana_alone_is_not_a_grandparent_claim():
    """Round 4: "nana" needs a possessive or a name nearby to read as a relation."""
    from immich_memories.titles.relationship_guard import refusing_unfounded_relationships
    from immich_memories.titles.title_suggestion import TitleSuggestion

    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [{"ids": ["person-a"], "name": "Mia Example"}],
        }
    )
    suggestion = TitleSuggestion(title="Afternoon snack: nana bread", subtitle=None)

    result = refusing_unfounded_relationships(suggestion, ["Mia Example"], "en", store)

    assert result is suggestion


def test_my_nana_with_no_record_is_refused():
    from immich_memories.titles.relationship_guard import refusing_unfounded_relationships
    from immich_memories.titles.title_suggestion import TitleSuggestion

    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [{"ids": ["person-a"], "name": "Mia Example"}],
        }
    )
    suggestion = TitleSuggestion(title="My nana Mia", subtitle=None)

    result = refusing_unfounded_relationships(suggestion, ["Mia Example"], "en", store)

    assert result is None


def test_korean_nae_nae_and_annae_are_not_the_possessive_nae():
    """Round 4: "내" ("my") must not fire inside "내내" or "안내"."""
    from immich_memories.titles.relationship_guard import refusing_unfounded_relationships
    from immich_memories.titles.title_suggestion import TitleSuggestion

    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [
                {
                    "ids": ["person-a"],
                    "name": "Yuri Example",
                    "confirmed": {"links": [{"kind": "grandparent-of", "with": "person-b"}]},
                },
                {"ids": ["person-b"], "name": "Bo Example"},
            ],
        }
    )
    suggestion = TitleSuggestion(title="내내 할머니와 안내", subtitle=None)

    result = refusing_unfounded_relationships(
        suggestion, ["Yuri Example", "Bo Example"], "ko", store
    )

    assert result is suggestion


def test_japanese_parents_and_aunt_by_marriage_are_compound_allowlisted():
    """Round 4: "父母" (parents) and "叔母" (aunt by marriage) protect 父/母."""
    from immich_memories.titles.relationship_guard import refusing_unfounded_relationships
    from immich_memories.titles.title_suggestion import TitleSuggestion

    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [{"ids": ["person-a"], "name": "Rin Example"}],
        }
    )
    suggestion = TitleSuggestion(title="父母と叔母とRin", subtitle=None)

    result = refusing_unfounded_relationships(suggestion, ["Rin Example"], "ja", store)

    assert result is suggestion


def test_chinese_maternal_grandparent_words_are_record_backed():
    """Round 4: 外婆/外公 are standard, not child's-eye, like 奶奶/爷爷."""
    from immich_memories.titles.relationship_guard import refusing_unfounded_relationships
    from immich_memories.titles.title_suggestion import TitleSuggestion

    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [
                {
                    "ids": ["person-a"],
                    "name": "Mei Example",
                    "confirmed": {"links": [{"kind": "grandparent-of", "with": "person-b"}]},
                },
                {"ids": ["person-b"], "name": "Bo Example"},
            ],
        }
    )
    suggestion = TitleSuggestion(title="外婆和Bo", subtitle=None)

    result = refusing_unfounded_relationships(
        suggestion, ["Mei Example", "Bo Example"], "zh-Hans", store
    )

    assert result is suggestion


def test_parent_of_backs_the_child_word_with_no_reciprocal_link():
    """Round 4: the inverse alias -- a recorded parent-of also backs "la fille de X"."""
    from immich_memories.titles.relationship_guard import refusing_unfounded_relationships
    from immich_memories.titles.title_suggestion import TitleSuggestion

    store = seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Zed Example"},
            "people": [
                {
                    "ids": ["person-mom"],
                    "name": "Rosa Example",
                    "confirmed": {"links": [{"kind": "parent-of", "with": "person-kid"}]},
                },
                # WHY: no reciprocal "child-of" link written on Lea's side --
                # the inverse alias must still back the word.
                {"ids": ["person-kid"], "name": "Lea Example"},
            ],
        }
    )
    suggestion = TitleSuggestion(title="Lea, la fille de Rosa", subtitle=None)

    result = refusing_unfounded_relationships(
        suggestion, ["Rosa Example", "Lea Example"], "fr", store
    )

    assert result is suggestion


def test_a_price_is_not_mistaken_for_a_year():
    """ "2024 €" is a price, not a year."""
    from immich_memories.titles.title_guards import refusing_a_wrong_year
    from immich_memories.titles.title_suggestion import TitleSuggestion

    suggestion = TitleSuggestion(title="Budget du voyage: 2024 €", subtitle=None)

    result = refusing_a_wrong_year(suggestion, "2010-01-01", "2010-12-31")

    assert result is suggestion


def test_de_helene_is_elided_h_muet_with_an_accent():
    from immich_memories.titles.title_guards import eliding_french
    from immich_memories.titles.title_suggestion import TitleSuggestion

    suggestion = TitleSuggestion(title="Un été de Hélène", subtitle=None)
    result = eliding_french(suggestion, "fr")

    assert result is not None
    assert result.title == "Un été d'Hélène"
