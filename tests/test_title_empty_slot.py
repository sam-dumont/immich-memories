"""A film title never carries an empty slot, a dangling preposition or an orphan separator (#2478).

A two-person film over a year, with no place, opened on "Robin and Kit in · 2025": the reader
wrote "Robin and Kit in 2025" and the separator meant for years run into the last name went in
after "in". These tests run canned reader answers through the real parsing and guards, and the
no-model template, in every film language.
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from immich_memories.config.loader import Config
from immich_memories.config.models.llm import LLMConfig
from immich_memories.i18n import SUPPORTED_LOCALES
from immich_memories.timeperiod import DateRange
from immich_memories.titles.film_title import template_title
from immich_memories.titles.llm_titles import generate_title_with_llm

NAMES = ["Robin", "Kit"]

# A reader's natural "<names> <preposition> <year>", per film language.
_NAMES_IN_THE_YEAR = {
    "en": "Robin and Kit in 2025",
    "fr": "Robin et Kit en 2025",
    "nl": "Robin en Kit in 2025",
    "de": "Robin und Kit in 2025",
    "es": "Robin y Kit en 2025",
    "it": "Robin e Kit nel 2025",
    "pt-BR": "Robin e Kit em 2025",
    "pt-PT": "Robin e Kit em 2025",
    "pl": "Robin i Kit w 2025",
    "sv": "Robin och Kit under 2025",
    "ru": "Robin и Kit в 2025",
    "ja": "RobinとKitの2025年",
    "zh-Hans": "Robin和Kit的2025年",
    "ko": "Robin과 Kit의 2025년",
}

# A reader's answer with the slot before the separator left empty, and its repair.
_EMPTY_SLOT = {
    "en": ("Robin and Kit in · 2025", "Robin and Kit · 2025"),
    "fr": ("Robin et Kit à · 2025", "Robin et Kit · 2025"),
    "nl": ("Robin en Kit in · 2025", "Robin en Kit · 2025"),
    "de": ("Robin und Kit im · 2025", "Robin und Kit · 2025"),
    "es": ("Robin y Kit en · 2025", "Robin y Kit · 2025"),
    "it": ("Robin e Kit a · 2025", "Robin e Kit · 2025"),
    "pt-BR": ("Robin e Kit em · 2025", "Robin e Kit · 2025"),
    "pt-PT": ("Robin e Kit no · 2025", "Robin e Kit · 2025"),
    "pl": ("Robin i Kit w · 2025", "Robin i Kit · 2025"),
    "sv": ("Robin och Kit i · 2025", "Robin och Kit · 2025"),
    "ru": ("Robin и Kit в · 2025", "Robin и Kit · 2025"),
    "ja": ("RobinとKitの · 2025年", "RobinとKit · 2025年"),
    "zh-Hans": ("Robin和Kit在 · 2025年", "Robin和Kit · 2025年"),
    "ko": ("Robin과 Kit의 · 2025년", "Robin과 Kit · 2025년"),
}


def test_every_film_language_is_covered():
    assert set(_NAMES_IN_THE_YEAR) == set(SUPPORTED_LOCALES)
    assert set(_EMPTY_SLOT) == set(SUPPORTED_LOCALES)


async def _titled(
    title: str, locale: str = "en", subtitle: str | None = None, names: list[str] = NAMES
):
    raw = json.dumps({"title": title, "subtitle": subtitle}, ensure_ascii=False)
    # WHY: replaces the reader, the only boundary these cases exercise.
    with patch(
        "immich_memories.titles.llm_titles.query_llm",
        new_callable=AsyncMock,
        return_value=raw,
    ):
        return await generate_title_with_llm(
            memory_type="multi_person",
            locale=locale,
            start_date="2025-01-01",
            end_date="2025-12-31",
            duration_days=364,
            person_names=names,
            llm_config=LLMConfig(
                enabled=True,
                provider="openai-compatible",
                base_url="http://localhost:8080/v1",
                model="omlx",
            ),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("locale", sorted(_NAMES_IN_THE_YEAR))
async def test_a_year_after_a_preposition_gets_no_separator(locale):
    """The separator sets years off a NAME; "in 2025" already reads as it should."""
    title = _NAMES_IN_THE_YEAR[locale]

    result = await _titled(title, locale)

    assert result is not None
    assert result.title == title
    assert "·" not in result.title


@pytest.mark.asyncio
@pytest.mark.parametrize("locale", sorted(_EMPTY_SLOT))
async def test_a_dangling_word_before_the_separator_is_dropped(locale):
    written, repaired = _EMPTY_SLOT[locale]

    result = await _titled(written, locale)

    assert result is not None
    assert result.title == repaired


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("written", "repaired"),
    [
        ("Robin and Kit ·  · 2025", "Robin and Kit · 2025"),
        ("Robin and Kit, · 2025", "Robin and Kit · 2025"),
        ("Robin and Kit at the · 2025", "Robin and Kit · 2025"),
        ("Robin and Kit, 2025 ·", "Robin and Kit, 2025"),
    ],
)
async def test_empty_segments_and_orphan_separators_are_closed(written, repaired):
    result = await _titled(written, subtitle=None)

    assert result is not None
    assert result.title == repaired


@pytest.mark.asyncio
async def test_a_title_ending_on_a_preposition_loses_it():
    result = await _titled("Robin and Kit in", subtitle="2025")

    assert result is not None
    assert result.title == "Robin and Kit"
    assert result.subtitle == "2025"


@pytest.mark.asyncio
async def test_a_years_range_run_into_the_last_name_still_gets_its_separator():
    result = await _titled("Robin and Kit 2025")

    assert result is not None
    assert result.title == "Robin and Kit · 2025"


@pytest.mark.asyncio
async def test_a_capitalised_word_is_a_name_not_a_dangling_article():
    """A person called An is not the article "an": only a lowercase function word dangles."""
    result = await _titled("Robin and An · 2025", names=["Robin", "An"])

    assert result is not None
    assert result.title == "Robin and An · 2025"


@pytest.mark.asyncio
async def test_a_subtitle_left_with_nothing_is_dropped():
    result = await _titled("Robin and Kit, 2025", subtitle="in ·")

    assert result is not None
    assert result.subtitle is None


@pytest.mark.parametrize("locale", SUPPORTED_LOCALES)
def test_the_no_model_title_names_the_year_and_both_people(locale):
    title, subtitle = template_title(
        Config(title_screens={"locale": locale}),
        memory_type="multi_person",
        date_range=DateRange(start=datetime(2025, 1, 1), end=datetime(2025, 12, 31, 23, 59, 59)),
        person_name=None,
        preset_params={"person_names": NAMES},
    )

    assert title == "2025"
    assert subtitle is not None
    assert "Robin" in subtitle
    assert "Kit" in subtitle
    assert subtitle.strip() == subtitle
    assert not subtitle.endswith(("&", "·", ","))
