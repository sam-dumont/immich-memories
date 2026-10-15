"""What an occasion memory tells the model before it names the film.

A special day, an album and a trip are named by the model from their own facts: the people
in them and what they are to each other, what the catalogue or the album owner called them.
These tests pin the facts that go in.
"""

from __future__ import annotations

from datetime import date

from immich_memories.db import Store
from immich_memories.titles.llm_titles import MemoryTitleFacts, build_title_prompt
from tests.people_registry_seed import seed_people


def _people_registry() -> Store:
    """A grandmother and a grandchild, the relation recorded in both directions."""
    return seed_people(
        {
            "owner": {"person_id": "person-owner", "name": "Alex Example"},
            "people": [
                {
                    "ids": ["person-ada"],
                    "name": "Ada Example",
                    "birth_date": "2024-02-07",
                    "confirmed": {
                        "links": [
                            {"kind": "grandchild-of", "with": "person-grace"},
                        ]
                    },
                },
                {
                    "ids": ["person-grace"],
                    "name": "Grace Example",
                    "birth_date": "1955-03-11",
                    "confirmed": {
                        "links": [
                            {"kind": "grandparent-of", "with": "person-ada"},
                        ]
                    },
                },
            ],
        }
    )


def test_a_special_day_is_told_what_the_catalogue_called_it():
    prompt = build_title_prompt(
        memory_type="special_day",
        locale="fr",
        start_date="2025-12-21",
        end_date="2025-12-21",
        duration_days=0,
        person_names=["Ada Example"],
        daily_locations=["2025-12-21: Brussels(6)"],
        facts=MemoryTitleFacts(
            occasion_name="an afternoon at a themed bowling alley",
            people_store=_people_registry(),
            today=date(2026, 9, 17),
        ),
    ).text

    assert "an afternoon at a themed bowling alley" in prompt
    assert "2025-12-21: Brussels(6)" in prompt
    assert "the name French gives that same place" in prompt  # the place-language rule


def test_an_album_memory_is_told_the_name_somebody_typed():
    prompt = build_title_prompt(
        memory_type="album",
        locale="en",
        start_date="2022-05-01",
        end_date="2022-05-03",
        duration_days=2,
        facts=MemoryTitleFacts(album_name="Old Negatives 75"),
    ).text

    assert "Old Negatives 75" in prompt


def test_a_trip_keeps_its_own_prompt():
    prompt = build_title_prompt(
        memory_type="trip",
        locale="en",
        start_date="2024-08-26",
        end_date="2024-09-04",
        duration_days=9,
        daily_locations=["2024-08-26: Nicosia (35.17, 33.36)"],
        country="Cyprus",
    ).text

    assert "Trip Pattern Classification" in prompt
    assert "trip_type" in prompt
