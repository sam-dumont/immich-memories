"""Each probe calls its production feature and checks the returned meaning."""

import asyncio
from functools import partial

from immich_memories.config_models_llm import LLMConfig
from immich_memories.conformance.runtime import Case
from immich_memories.titles.llm_titles import generate_title_with_llm


def title(llm: LLMConfig) -> str:
    answer = asyncio.run(
        generate_title_with_llm(
            "monthly_highlights",
            "en",
            "2030-06-01",
            "2030-06-30",
            30,
            clip_descriptions=["A chess tournament, with chessboards, clocks and a trophy."],
            llm_config=llm,
        )
    )
    assert answer is not None, "title response could not be parsed"
    assert "chess" in answer.title.casefold(), "title did not name the chess tournament"
    return "title names the chess tournament"


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
    )
