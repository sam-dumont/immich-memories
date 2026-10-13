"""A film about several people names every one of them in its opening title.

`generate --memory-type multi_person --person Robin --person Kit` once opened on "Kit in 2025":
the reader dropped Robin, and whether both names made it in was up to the model. A model title
that leaves someone out falls back to the rules title, which names the whole cast in its
subtitle in every film language. These tests run canned reader answers through the real
prompt, parsing and guards, and the no-model template.
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from immich_memories.config_loader import Config
from immich_memories.config_models_llm import LLMConfig
from immich_memories.i18n import SUPPORTED_LOCALES
from immich_memories.timeperiod import DateRange
from immich_memories.titles.film_title import template_title
from immich_memories.titles.llm_titles import build_title_prompt, generate_title_with_llm

TWO = ["Robin", "Kit"]
THREE = ["Robin", "Kit", "Sam"]

# A reader's answer naming one of the two people, per language.
_ONE_OF_TWO = {
    "en": "Kit in 2025",
    "fr": "Kit en 2025",
    "de": "Kit in 2025",
    "es": "Kit en 2025",
    "pl": "Kit w 2025",
    "ru": "Kit в 2025",
    "ja": "Kitの2025年",
    "ko": "Kit의 2025년",
}

# The same answer naming both, joined with the language's own "and".
_BOTH = {
    "en": "Robin and Kit in 2025",
    "fr": "Robin et Kit en 2025",
    "de": "Robin und Kit in 2025",
    "es": "Robin y Kit en 2025",
    "pl": "Robin i Kit w 2025",
    "ru": "Robin и Kit в 2025",
    "ja": "RobinとKitの2025年",
    "ko": "Robin과 Kit의 2025년",
    "zh-Hans": "Robin和Kit的2025年",
}


async def _titled(
    title: str,
    locale: str = "en",
    subtitle: str | None = None,
    names: list[str] = TWO,
    memory_type: str = "multi_person",
):
    raw = json.dumps({"title": title, "subtitle": subtitle}, ensure_ascii=False)
    # WHY: replaces the reader, the only boundary these cases exercise.
    with patch(
        "immich_memories.titles.llm_titles.query_llm",
        new_callable=AsyncMock,
        return_value=raw,
    ):
        return await generate_title_with_llm(
            memory_type=memory_type,
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


def _no_model_title(names: list[str], locale: str) -> tuple[str, str | None]:
    return template_title(
        Config(title_screens={"locale": locale}),
        memory_type="multi_person",
        date_range=DateRange(start=datetime(2025, 1, 1), end=datetime(2025, 12, 31, 23, 59, 59)),
        person_name=None,
        preset_params={"person_names": names},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("locale", sorted(_ONE_OF_TWO))
async def test_a_title_naming_one_of_two_people_falls_back_to_the_rules_title(locale):
    result = await _titled(_ONE_OF_TWO[locale], locale)

    assert result is None
    title, subtitle = _no_model_title(TWO, locale)
    shown = f"{title} {subtitle}"
    assert "Robin" in shown
    assert "Kit" in shown


@pytest.mark.asyncio
@pytest.mark.parametrize("locale", sorted(_BOTH))
async def test_a_title_naming_both_people_passes_untouched(locale):
    result = await _titled(_BOTH[locale], locale)

    assert result is not None
    assert result.title == _BOTH[locale]


@pytest.mark.asyncio
async def test_a_name_may_sit_in_the_subtitle():
    """The rules title puts the cast in the subtitle; a model title may too."""
    result = await _titled("Kit in 2025", subtitle="Robin")

    assert result is not None
    assert (result.title, result.subtitle) == ("Kit in 2025", "Robin")


@pytest.mark.asyncio
async def test_a_full_name_is_named_by_its_first_name():
    result = await _titled("Robin and Kit in 2025", names=["Robin Example", "Kit Example"])

    assert result is not None
    assert result.title == "Robin and Kit in 2025"


@pytest.mark.asyncio
async def test_a_name_written_without_its_accent_still_counts():
    result = await _titled("Robin et Chloe en 2025", "fr", names=["Robin", "Chloé"])

    assert result is not None


@pytest.mark.asyncio
async def test_a_name_inside_another_word_does_not_count():
    """ "Kitchen" is not Kit."""
    result = await _titled("Robin in the Kitchen, 2025", names=["Robin", "Kit"])

    assert result is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("locale", "written"),
    [
        ("en", "Robin and Kit in 2025"),
        ("fr", "Robin et Sam en 2025"),
        ("de", "Kit und Sam in 2025"),
    ],
)
async def test_a_title_naming_two_of_three_people_falls_back(locale, written):
    result = await _titled(written, locale, names=THREE)

    assert result is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("locale", "title", "subtitle"),
    [
        ("en", "Robin, Kit and Sam in 2025", None),
        ("fr", "Robin, Kit et Sam en 2025", None),
        ("es", "2025 en familia", "Robin, Kit y Sam"),
        ("ja", "RobinとKitとSamの2025年", None),
    ],
)
async def test_three_people_are_named_in_the_title_or_the_subtitle(locale, title, subtitle):
    result = await _titled(title, locale, subtitle=subtitle, names=THREE)

    assert result is not None
    assert (result.title, result.subtitle) == (title, subtitle)


@pytest.mark.asyncio
async def test_a_one_person_spotlight_is_not_asked_to_name_anyone_else():
    """A spotlight follows one person; the guard is for a film about several."""
    result = await _titled(
        "Kit in 2025", memory_type="person_spotlight", names=["Kit"], subtitle=None
    )

    assert result is not None


@pytest.mark.parametrize("locale", SUPPORTED_LOCALES)
def test_the_no_model_title_names_all_three_people(locale):
    title, subtitle = _no_model_title(THREE, locale)

    assert title == "2025"
    assert subtitle is not None
    for name in THREE:
        assert name in subtitle


def test_the_people_prompt_asks_for_every_name():
    prompt = build_title_prompt(
        memory_type="multi_person",
        locale="en",
        start_date="2025-01-01",
        end_date="2025-12-31",
        duration_days=364,
        person_names=TWO,
    )

    assert "every person" in prompt.text.casefold()
