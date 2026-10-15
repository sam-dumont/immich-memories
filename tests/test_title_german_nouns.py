"""German capitalises every noun, so a capital alone does not make a word a name.

A German film titled "Robin und Kit im Jahr 2025" fell back to the rules title because "Jahr"
named nobody in the film (#2504). These tests run canned reader answers through the real
prompt, parsing and guard chain: a German title of plain nouns passes, a German title that
invents a person is still refused, and English and French keep reading a capital as a name.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from immich_memories.config_models_llm import LLMConfig
from immich_memories.titles.llm_titles import MemoryTitleFacts, generate_title_with_llm
from immich_memories.titles.title_guards import invented_name

_LLM = LLMConfig(
    enabled=True, provider="openai-compatible", base_url="http://localhost:8080/v1", model="omlx"
)


async def _titled(
    title: str,
    *,
    locale: str = "de",
    subtitle: str | None = None,
    names: tuple[str, ...] = ("Robin", "Kit"),
    memory_type: str = "multi_person",
    span: tuple[str, str] = ("2025-01-01", "2025-12-31"),
    facts: MemoryTitleFacts | None = None,
):
    raw = json.dumps({"title": title, "subtitle": subtitle}, ensure_ascii=False)
    # WHY: replaces the reader, the only boundary these cases exercise.
    with patch(
        "immich_memories.titles.llm_titles.query_llm", new_callable=AsyncMock, return_value=raw
    ):
        return await generate_title_with_llm(
            memory_type=memory_type,
            locale=locale,
            start_date=span[0],
            end_date=span[1],
            duration_days=1,
            person_names=list(names),
            facts=facts,
            llm_config=_LLM,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("title", "subtitle", "span"),
    [
        ("Robin und Kit im Jahr 2025", None, ("2025-01-01", "2025-12-31")),
        ("Sommer 2025", "Robin und Kit", ("2025-06-01", "2025-08-31")),
        ("Robin und Kit im Sommer 2025", None, ("2025-06-01", "2025-08-31")),
        ("Ein Tag am See", "Robin und Kit, 2025", ("2025-07-12", "2025-07-12")),
        ("Robin und Kit, ein Tag am See", "2025", ("2025-07-12", "2025-07-12")),
    ],
)
async def test_a_german_title_of_plain_nouns_passes(title, subtitle, span):
    result = await _titled(title, subtitle=subtitle, span=span)

    assert result is not None
    assert (result.title, result.subtitle) == (title, subtitle)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("title", "subtitle"),
    [
        ("Robin und Max im Jahr 2025", None),
        ("Robin, Kit und Max am See 2025", None),
        ("Robin und Kit im Jahr 2025", "Ein Tag mit Max"),
    ],
)
async def test_a_german_title_inventing_a_person_is_still_refused(title, subtitle):
    result = await _titled(title, subtitle=subtitle)

    if subtitle is None:
        assert result is None
    else:
        assert result is not None
        assert (result.title, result.subtitle) == (title, None)


def test_a_german_title_inventing_a_place_is_still_caught():
    facts = "Span: 2025-07-12 to 2025-07-12 (1 day)\nPlaces by day:\n  07-12: Annecy\n"
    assert invented_name("Ein Tag am See in Annecy", facts, "de") is None
    assert invented_name("Ein Tag am See in Kroatien", facts, "de") == "Kroatien"
    assert invented_name("Ein Tag in Heidelberg", facts, "de") == "Heidelberg"


@pytest.mark.parametrize(
    ("locale", "title", "invented"),
    [
        ("en", "Robin and Kit at the Lake 2025", "Lake"),
        ("en", "Robin and Max in 2025", "Max"),
        ("fr", "Robin et Kit au Lac 2025", "Lac"),
        ("fr", "Robin et Max en 2025", "Max"),
    ],
)
def test_english_and_french_still_read_a_capital_as_a_name(locale, title, invented):
    facts = "People: Robin, Kit\nSpan: 2025-01-01 to 2025-12-31 (364 days)\n"
    assert invented_name(title, facts, locale) == invented


def test_a_german_noun_is_only_a_noun_in_german():
    facts = "People: Robin, Kit\nSpan: 2025-01-01 to 2025-12-31 (364 days)\n"
    assert invented_name("Robin und Kit im Jahr 2025", facts, "de") is None
    assert invented_name("Robin und Kit im Jahr 2025", facts, "en") == "Jahr"
