"""Each probe calls its production feature and checks the returned meaning."""

import asyncio
from functools import partial

from immich_memories.config_models_llm import LLMConfig
from immich_memories.conformance.audience_cases import audience_cases
from immich_memories.conformance.catalogue_cases import catalogue_cases
from immich_memories.conformance.editorial_cases import editorial_cases
from immich_memories.conformance.episode_cases import episode_cases
from immich_memories.conformance.fixtures import scratch_store
from immich_memories.conformance.free_text_cases import free_text_cases
from immich_memories.conformance.lexical_cases import lexical_cases
from immich_memories.conformance.music_cases import music_cases
from immich_memories.conformance.occasion_cases import occasion_cases
from immich_memories.conformance.runtime import Case
from immich_memories.conformance.vision_cases import vision_cases
from immich_memories.titles.llm_titles import MemoryTitleFacts, generate_title_with_llm


def title(llm: LLMConfig) -> str:
    answer = asyncio.run(
        generate_title_with_llm(
            "special_day",
            "en",
            "2030-06-01",
            "2030-06-01",
            1,
            facts=MemoryTitleFacts(occasion_name="Chess tournament"),
            llm_config=llm,
        )
    )
    assert answer is not None, "title response could not be parsed"
    assert "chess" in answer.title.casefold(), "title did not name the chess tournament"
    return "title names the chess tournament"


def trip_title(llm: LLMConfig) -> str:
    answer = asyncio.run(
        generate_title_with_llm(
            "trip",
            "en",
            "2030-06-01",
            "2030-06-07",
            7,
            daily_locations=[
                "Day 1: driving from Reykjavik to Vik",
                "Day 3: driving onward to Hofn",
                "Day 5: driving onward to Akureyri",
            ],
            country="Iceland",
            facts=MemoryTitleFacts(place="Iceland"),
            clip_descriptions=["A week driving around Iceland, moving to a new town each night."],
            llm_config=llm,
        )
    )
    assert answer is not None and "iceland" in answer.title.lower(), (
        "trip title lost its recorded place"
    )
    assert answer.trip_type == "road_trip", "driving itinerary was not classified as a road trip"
    assert answer.map_mode is not None, "trip returned no valid map mode"
    return "names Iceland and classifies the moving driving itinerary"


def people_title(llm: LLMConfig) -> str:
    with scratch_store() as (_, store):
        answer = asyncio.run(
            generate_title_with_llm(
                "person_spotlight",
                "en",
                "2030-01-01",
                "2030-12-31",
                365,
                person_names=["Avery Example"],
                facts=MemoryTitleFacts(people_store=store),
                llm_config=llm,
            )
        )
    assert answer is not None and "avery" in answer.title.lower(), (
        "people title lost the named person"
    )
    return "names the synthetic person without inventing a family relationship"


def cases(llm: LLMConfig) -> tuple[Case, ...]:
    return (
        Case(
            "titles",
            partial(title, llm),
            frozenset(
                {
                    "titles.llm_titles:generate_title_with_llm",
                }
            ),
        ),
        Case(
            "trip title and route",
            partial(trip_title, llm),
            frozenset({"titles.llm_titles:generate_title_with_llm"}),
        ),
        Case(
            "people title",
            partial(people_title, llm),
            frozenset({"titles.llm_titles:generate_title_with_llm"}),
        ),
        *free_text_cases(llm),
        *lexical_cases(llm),
        *occasion_cases(llm),
        *music_cases(llm),
        *vision_cases(llm),
        *catalogue_cases(llm),
        *episode_cases(llm),
        *editorial_cases(llm),
        *audience_cases(llm),
    )
