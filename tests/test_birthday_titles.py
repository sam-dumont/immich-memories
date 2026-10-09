"""An annual birthday film keeps its year even when its search includes flashbacks."""

import json
from datetime import datetime

import pytest

from immich_memories.config_loader import Config
from immich_memories.generate import GenerationParams
from immich_memories.generate_settings import build_title_settings
from immich_memories.timeperiod import DateRange
from immich_memories.titles.film_title import template_title


@pytest.mark.parametrize("locale", ["en", "fr"])
@pytest.mark.parametrize("start_year", [2023, 2019])
def test_birthday_template_and_render_name_the_celebrated_year(tmp_path, locale, start_year):
    config = Config(title_screens={"locale": locale})
    span = DateRange(start=datetime(start_year, 2, 8), end=datetime(2024, 2, 7, 23, 59, 59))
    params = {"birthday": True, "person_names": ["Riley"]}
    title = template_title(
        config,
        memory_type="person_spotlight",
        date_range=span,
        person_name="Riley",
        preset_params=params,
    )
    assert title[0] == "2024"
    assert "Riley" in title[1]
    rendered = build_title_settings(
        GenerationParams(
            clips=[],
            output_path=tmp_path / "film.mp4",
            config=config,
            memory_type="person_spotlight",
            memory_preset_params=params,
            person_name="Riley",
            date_start=span.start.date(),
            date_end=span.end.date(),
        ),
        config,
        [],
    )
    assert (rendered.title_override, rendered.subtitle_override) == title


@pytest.mark.asyncio
@pytest.mark.parametrize("year_in_title", [False, True])
async def test_model_cannot_drop_the_birthday_year(year_in_title):
    from unittest.mock import AsyncMock, patch

    from immich_memories.config_models_llm import LLMConfig
    from immich_memories.titles.llm_titles import generate_title_with_llm, memory_title_facts

    # WHY: the remote model is the only boundary; parsing and all title guards run normally.
    with patch(
        "immich_memories.titles.llm_titles.query_llm",
        new_callable=AsyncMock,
        return_value=json.dumps(
            {"title": "Riley's birthday", "subtitle": "2024" if year_in_title else None}
        ),
    ) as query:
        result = await generate_title_with_llm(
            memory_type="person_spotlight",
            locale="en",
            start_date="2019-02-06",
            end_date="2024-02-07",
            duration_days=1827,
            person_names=["Riley"],
            facts=memory_title_facts({"birthday": True}),
            llm_config=LLMConfig(enabled=True, model="test-model", base_url="http://llm.test/v1"),
        )
    if year_in_title:
        assert result is not None
        assert "2024" in f"{result.title} {result.subtitle}"
    else:
        assert result is None
    assert "Year(s) the title or subtitle must show: 2024" in query.call_args.args[0]


def test_public_birthday_command_keeps_its_annual_title_context(tmp_path):
    from tests.test_people_expression_cli import PEOPLE, Client, invoke

    class BirthdayClient(Client):
        def get_person_by_name(self, name):
            return next(person for person in PEOPLE if person.name == name)

    result, _, pipeline = invoke(
        tmp_path,
        [
            "--memory-type",
            "person_spotlight",
            "--year",
            "2024",
            "--birthday",
            "05-04",
            "--person",
            "Adult A",
            "--no-music",
            "--no-live-photos",
        ],
        BirthdayClient(),
    )
    assert result.exit_code == 0, (result.output, result.exception)
    request = pipeline.call_args.kwargs
    title, _ = template_title(
        Config(title_screens={"locale": "en"}),
        memory_type=request["memory_type"],
        date_range=request["date_range"],
        person_name="Adult A",
        preset_params=request["memory_preset_params"],
    )
    assert title == "2024"
