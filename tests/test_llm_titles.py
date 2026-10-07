"""Tests for LLM title generation and response parsing."""

from __future__ import annotations

import json
from datetime import date

import pytest


class TestParseTitleResponse:
    """Parse LLM JSON response into TitleSuggestion."""

    def test_parses_valid_json(self):
        from immich_memories.titles.llm_titles import parse_title_response
        from immich_memories.titles.title_suggestion import TitleSuggestion

        raw = '{"title": "A Week in Bretagne", "subtitle": "From Brasparts to Frehel", "trip_type": "multi_base", "map_mode": "excursions", "map_mode_reason": "Two bases"}'
        result = parse_title_response(raw)
        assert isinstance(result, TitleSuggestion)
        assert result.title == "A Week in Bretagne"
        assert result.subtitle == "From Brasparts to Frehel"
        assert result.trip_type == "multi_base"
        assert result.map_mode == "excursions"

    def test_strips_markdown_code_block(self):
        from immich_memories.titles.llm_titles import parse_title_response

        raw = '```json\n{"title": "Summer 2024", "subtitle": null, "trip_type": null, "map_mode": null, "map_mode_reason": null}\n```'
        result = parse_title_response(raw)
        assert result is not None
        assert result.title == "Summer 2024"

    def test_rejects_invalid_trip_type(self):
        from immich_memories.titles.llm_titles import parse_title_response

        raw = '{"title": "Trip", "subtitle": null, "trip_type": "invalid_type", "map_mode": null, "map_mode_reason": null}'
        result = parse_title_response(raw)
        assert result is not None
        assert result.trip_type is None

    def test_truncates_long_title(self):
        from immich_memories.titles.llm_titles import parse_title_response

        raw = (
            '{"title": "'
            + "A" * 200
            + '", "subtitle": null, "trip_type": null, "map_mode": null, "map_mode_reason": null}'
        )
        result = parse_title_response(raw)
        assert result is not None
        assert len(result.title) <= 80

    def test_returns_none_on_malformed_json(self):
        from immich_memories.titles.llm_titles import parse_title_response

        assert parse_title_response("not json at all") is None
        assert parse_title_response("") is None

    def test_returns_none_on_missing_title(self):
        from immich_memories.titles.llm_titles import parse_title_response

        raw = '{"subtitle": "no title field"}'
        assert parse_title_response(raw) is None


class TestPeopleTitleFactsStatesTheCountUnambiguously:
    """A bare "1" still let a small model pluralise ("ses petits-enfants" for one
    grandchild, in a real French title); the facts must say "one person" outright.
    """

    def test_one_person_is_spelled_out_as_singular(self):
        from immich_memories.titles.llm_titles import people_title_facts

        facts = people_title_facts(["Ada Example"], date(2024, 1, 1), date(2024, 12, 31))
        assert "People in the film: one person, singular" in facts

    def test_two_people_still_get_a_plain_number(self):
        from immich_memories.titles.llm_titles import people_title_facts

        facts = people_title_facts(
            ["Ada Example", "Noah Example"], date(2024, 1, 1), date(2024, 12, 31)
        )
        assert "People in the film: 2" in facts


class TestMemoryTitleFactsReadsAWrittenSubject:
    """An `--ask` subject pool (#2064) and a `--subject` album both carry their
    subject as `occasion_name`, so the title prompt can reword it, in the film's
    language, the same way it already rewords a special day's catalogue title."""

    def test_a_written_subject_becomes_the_occasion_name(self):
        from immich_memories.titles.llm_titles import memory_title_facts

        facts = memory_title_facts({"album_id": "ask-1", "subject": "landscapes, no humans"})

        assert facts.occasion_name == "landscapes, no humans"

    def test_a_catalogued_title_still_wins_over_a_subject(self):
        from immich_memories.titles.llm_titles import memory_title_facts

        facts = memory_title_facts({"title": "A day at the lake", "subject": "lake day"})

        assert facts.occasion_name == "A day at the lake"

    def test_no_subject_and_no_catalogue_leaves_the_occasion_unnamed(self):
        from immich_memories.titles.llm_titles import memory_title_facts

        facts = memory_title_facts({"album_name": "Trip 2025", "album_id": "a-1"})

        assert facts.occasion_name is None


class TestBuildTitlePrompt:
    """Build context-rich prompt for the LLM."""

    def test_trip_prompt_includes_bases_and_descriptions(self):
        from immich_memories.titles.llm_titles import build_title_prompt

        prompt = build_title_prompt(
            memory_type="trip",
            locale="en",
            start_date="2023-09-23",
            end_date="2023-09-29",
            duration_days=7,
            daily_locations=[
                "2023-09-23: Brasparts (48.30, -3.96)",
                "2023-09-24: Camaret (48.28, -4.59)",
                "2023-09-27: Frehel (48.69, -2.34)",
            ],
            country="France",
            clip_descriptions=["hiking along cliffs", "sunset over bay"],
            smart_objects=["person", "beach"],
        ).text
        assert "trip" in prompt.lower()
        assert "Brasparts" in prompt
        assert "French" not in prompt  # locale=en → English
        assert "hiking along cliffs" in prompt

    def test_person_prompt_includes_names(self, tmp_path):
        from immich_memories.db import open_store
        from immich_memories.titles.llm_titles import MemoryTitleFacts, build_title_prompt

        empty_record = open_store()

        prompt = build_title_prompt(
            memory_type="multi_person",
            locale="fr",
            start_date="2019-01-01",
            end_date="2025-12-31",
            duration_days=2556,
            person_names=["Ada Example", "Noah Example"],
            clip_descriptions=["playing in park", "birthday party"],
            facts=MemoryTitleFacts(people_store=empty_record),
        ).text
        assert "Ada Example" in prompt
        assert "Noah Example" in prompt
        assert "French" in prompt

    def test_includes_rules(self):
        from immich_memories.titles.llm_titles import build_title_prompt

        prompt = build_title_prompt(
            memory_type="trip",
            locale="en",
            start_date="2024-01-01",
            end_date="2024-12-31",
            duration_days=366,
        ).text
        assert "Rules" in prompt
        assert "weekend" in prompt.lower()

    @pytest.mark.parametrize("memory_type", ["special_day", "trip", "multi_person"])
    def test_the_album_the_pictures_sit_in_reaches_every_prompt(self, memory_type, tmp_path):
        """What somebody filed the day under is a fact, whatever kind of film it is."""
        from immich_memories.db import open_store
        from immich_memories.titles.llm_titles import MemoryTitleFacts, build_title_prompt

        empty_record = open_store()

        prompt = build_title_prompt(
            memory_type=memory_type,
            locale="en",
            start_date="2022-03-27",
            end_date="2022-03-27",
            duration_days=0,
            person_names=["Ada Example"],
            facts=MemoryTitleFacts(album_name="Lakeside Half 2022", people_store=empty_record),
        ).text

        assert "Lakeside Half 2022" in prompt


class TestGenerateTitleWithLlm:
    """End-to-end: build prompt, query LLM, parse response."""

    @pytest.mark.asyncio
    async def test_returns_title_suggestion_on_success(self):
        from unittest.mock import AsyncMock, patch

        from immich_memories.config_models_llm import LLMConfig
        from immich_memories.titles.llm_titles import generate_title_with_llm
        from immich_memories.titles.title_suggestion import TitleSuggestion

        config = LLMConfig(
            enabled=True,
            provider="openai-compatible",
            base_url="http://localhost:8080/v1",
            model="omlx",
        )
        llm_response = '{"title": "Summer in Crete, 2019", "subtitle": "Chania to Sitia", "trip_type": "multi_base", "map_mode": "excursions", "map_mode_reason": "Two bases"}'

        with patch(
            "immich_memories.titles.llm_titles.query_llm",
            new_callable=AsyncMock,
            return_value=llm_response,
        ):
            result = await generate_title_with_llm(
                memory_type="trip",
                locale="en",
                start_date="2019-07-04",
                end_date="2019-07-14",
                duration_days=11,
                daily_locations=[
                    "2019-07-04: Platanos (35.50, 23.96)",
                    "2019-07-10: Sitia (35.19, 26.10)",
                ],
                country="Greece",
                llm_config=config,
            )

        assert isinstance(result, TitleSuggestion)
        assert result.title == "Summer in Crete, 2019"
        assert result.map_mode == "excursions"

    @pytest.mark.asyncio
    async def test_returns_none_on_llm_failure(self):
        from unittest.mock import AsyncMock, patch

        import httpx

        from immich_memories.config_models_llm import LLMConfig
        from immich_memories.titles.llm_titles import generate_title_with_llm

        config = LLMConfig(
            enabled=True,
            provider="openai-compatible",
            base_url="http://localhost:8080/v1",
            model="omlx",
        )

        with patch(
            "immich_memories.titles.llm_titles.query_llm",
            new_callable=AsyncMock,
            side_effect=httpx.HTTPError("timeout"),
        ):
            result = await generate_title_with_llm(
                memory_type="year",
                locale="en",
                start_date="2024-01-01",
                end_date="2024-12-31",
                duration_days=366,
                llm_config=config,
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_config(self):
        from immich_memories.titles.llm_titles import generate_title_with_llm

        result = await generate_title_with_llm(
            memory_type="year",
            locale="en",
            start_date="2024-01-01",
            end_date="2024-12-31",
            duration_days=366,
            llm_config=None,
        )
        assert result is None


class TestTitleGenerationThinks:
    @pytest.mark.asyncio
    async def test_title_query_opts_into_thinking(self):
        """A title is a judgement call — the query asks the model to reason;
        the query layer then honors it only when llm.thinking says the server can."""
        from unittest.mock import AsyncMock, patch

        from immich_memories.config_models_llm import LLMConfig
        from immich_memories.titles.llm_titles import generate_title_with_llm

        config = LLMConfig(
            enabled=True,
            base_url="http://localhost:8080/v1",
            provider="openai-compatible",
            model="qwen",
            thinking=True,
        )
        # WHY: query_llm is the boundary to the LLM server; only the request is under test.
        with patch(
            "immich_memories.titles.llm_titles.query_llm",
            new_callable=AsyncMock,
            return_value='{"title": "A Long Saturday", "subtitle": ""}',
        ) as mock_query:
            await generate_title_with_llm(
                memory_type="monthly_highlights",
                locale="en",
                start_date="2019-07-01",
                end_date="2019-07-31",
                duration_days=31,
                daily_locations=[],
                llm_config=config,
            )

        assert mock_query.call_args.kwargs.get("thinking") is True


class TestATitleMayOnlyNameWhatTheFactsName:
    """The reader may reword the facts; it may not add names to them."""

    @staticmethod
    def _config():
        from immich_memories.config_models_llm import LLMConfig

        return LLMConfig(
            enabled=True,
            provider="openai-compatible",
            base_url="http://localhost:8080/v1",
            model="omlx",
        )

    @staticmethod
    async def _titled(raw: str, **kwargs):
        from unittest.mock import AsyncMock, patch

        from immich_memories.titles.llm_titles import MemoryTitleFacts, generate_title_with_llm

        # WHY: replaces the reader, the only boundary these cases exercise.
        with patch(
            "immich_memories.titles.llm_titles.query_llm",
            new_callable=AsyncMock,
            return_value=raw,
        ):
            return await generate_title_with_llm(
                memory_type="special_day",
                locale=kwargs.pop("locale", "en"),
                start_date="2022-03-27",
                end_date="2022-03-27",
                duration_days=0,
                facts=MemoryTitleFacts(album_name="Lakeside Half 2022"),
                llm_config=TestATitleMayOnlyNameWhatTheFactsName._config(),
                **kwargs,
            )

    @pytest.mark.asyncio
    async def test_a_title_naming_something_no_fact_names_is_refused(self):
        assert await self._titled('{"title": "Sunday at Ravenscourt", "subtitle": null}') is None

    @pytest.mark.asyncio
    async def test_a_title_built_from_the_facts_stands(self):
        result = await self._titled('{"title": "Lakeside Half 2022", "subtitle": null}')

        assert result is not None
        assert result.title == "Lakeside Half 2022"

    @pytest.mark.asyncio
    async def test_a_place_spelled_the_way_the_film_speaks_is_not_an_invention(self):
        result = await self._titled(
            '{"title": "Le semi de Bruxelles, 2022", "subtitle": null}',
            locale="fr",
            daily_locations=["2022-03-27: Brussels (50.85, 4.35)"],
        )

        assert result is not None
        assert result.title == "Le semi de Bruxelles, 2022"

    @pytest.mark.asyncio
    async def test_a_subtitle_stating_what_no_fact_states_is_dropped_not_the_title(self):
        result = await self._titled(
            '{"title": "Lakeside Half 2022", "subtitle": "Finishing in Ravenscourt"}'
        )

        assert result is not None
        assert result.title == "Lakeside Half 2022"
        assert result.subtitle is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "subtitle",
        ["Salt air and golden light", "Quiet mornings by the sea", "Une douceur infinie"],
    )
    async def test_a_subtitle_naming_a_mood_no_fact_carries_is_dropped(self, subtitle):
        result = await self._titled(f'{{"title": "Lakeside Half 2022", "subtitle": "{subtitle}"}}')

        assert result is not None
        assert result.title == "Lakeside Half 2022"
        assert result.subtitle is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "subtitle", ["Lakeside Half, 27 March", "27 mars 2022", "Sunday 27 March"]
    )
    async def test_a_subtitle_of_dates_and_the_facts_own_words_stands(self, subtitle):
        result = await self._titled(f'{{"title": "Lakeside Half 2022", "subtitle": "{subtitle}"}}')

        assert result is not None
        assert result.subtitle == subtitle


class TestAYearRangeIsSeparatedFromTheNames:
    """A multi-person title that runs the years straight into the last name reads as one name (#2082)."""

    NAMES = ["Anna", "Ben", "Chloé", "Dan"]

    @classmethod
    async def _titled(cls, title: str, names=None, locale="en"):
        from unittest.mock import AsyncMock, patch

        from immich_memories.titles.llm_titles import generate_title_with_llm

        raw = f'{{"title": "{title}", "subtitle": null}}'
        # WHY: replaces the reader, the only boundary these cases exercise.
        with patch(
            "immich_memories.titles.llm_titles.query_llm",
            new_callable=AsyncMock,
            return_value=raw,
        ):
            return await generate_title_with_llm(
                memory_type="multi_person",
                locale=locale,
                start_date="2013-01-01",
                end_date="2026-06-30",
                duration_days=4929,
                person_names=cls.NAMES if names is None else names,
                llm_config=TestATitleMayOnlyNameWhatTheFactsName._config(),
            )

    @pytest.mark.asyncio
    async def test_the_years_get_a_separator_after_the_last_name(self):
        result = await self._titled("Anna, Ben, Chloé and Dan 2013-2026")

        assert result is not None
        assert result.title == "Anna, Ben, Chloé and Dan \u00b7 2013-2026"

    @pytest.mark.asyncio
    async def test_a_french_title_is_separated_the_same_way(self):
        result = await self._titled("Anna, Ben, Chloé et Dan 2013-2026", locale="fr")

        assert result is not None
        assert result.title == "Anna, Ben, Chloé et Dan \u00b7 2013-2026"

    @pytest.mark.asyncio
    async def test_a_title_that_already_separates_them_is_left_alone(self):
        result = await self._titled("Anna, Ben, Chloé and Dan, 2013-2026")

        assert result is not None
        assert result.title == "Anna, Ben, Chloé and Dan, 2013-2026"

    @pytest.mark.asyncio
    async def test_a_single_person_title_is_not_touched(self):
        result = await self._titled("Anna 2013-2026", names=["Anna"])

        assert result is not None
        assert result.title == "Anna 2013-2026"


class TestATitleKeepsTheYearTheTemplateWouldShow:
    """A model title must carry exactly the year(s) the BASIC template's own
    title would show for the same memory, derived through the renderer's own
    dispatch (`infer_selection_type` then `generate_title`) — not a fixed list.

    The template shows no year for "on this day", a person spotlight spanning
    several years (it opens on the name alone) and a holiday (named off
    `holiday_label`, never dated). Every other shape — a calendar year, a
    season, a single-year person spotlight or multi-person film, a plain
    date range, a trip — carries its year, and the model must too.
    """

    @staticmethod
    def _config():
        from immich_memories.config_models_llm import LLMConfig

        return LLMConfig(
            enabled=True,
            provider="openai-compatible",
            base_url="http://localhost:8080/v1",
            model="omlx",
        )

    @staticmethod
    async def _titled(raw: str, *, memory_type: str, start_date: str, end_date: str, **kwargs):
        from unittest.mock import AsyncMock, patch

        from immich_memories.titles.llm_titles import MemoryTitleFacts, generate_title_with_llm

        duration_days = (date.fromisoformat(end_date) - date.fromisoformat(start_date)).days
        # WHY: replaces the reader, the only boundary these cases exercise.
        with patch(
            "immich_memories.titles.llm_titles.query_llm",
            new_callable=AsyncMock,
            return_value=raw,
        ):
            return await generate_title_with_llm(
                memory_type=memory_type,
                locale=kwargs.pop("locale", "en"),
                start_date=start_date,
                end_date=end_date,
                duration_days=duration_days,
                facts=kwargs.pop("facts", MemoryTitleFacts()),
                llm_config=TestATitleKeepsTheYearTheTemplateWouldShow._config(),
                **kwargs,
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("memory_type", "start_date", "end_date", "kwargs"),
        [
            ("season", "2024-06-01", "2024-08-31", {}),
            ("year_in_review", "2024-01-01", "2024-12-31", {}),
            ("person_spotlight", "2024-01-01", "2024-06-01", {"person_names": ["Mila"]}),
            ("multi_person", "2024-01-01", "2024-12-31", {}),
            ("album", "2024-03-01", "2024-04-15", {}),
            ("trip", "2024-06-01", "2024-06-07", {}),
        ],
        ids=[
            "season",
            "calendar_year",
            "single_year_person_spotlight",
            "multi_person_with_a_year",
            "plain_date_range",
            "trip",
        ],
    )
    async def test_a_yearless_title_is_refused(self, memory_type, start_date, end_date, kwargs):
        from immich_memories.titles.llm_titles import MemoryTitleFacts

        result = await self._titled(
            '{"title": "A lovely time together", "subtitle": null}',
            memory_type=memory_type,
            start_date=start_date,
            end_date=end_date,
            facts=MemoryTitleFacts(),
            **kwargs,
        )
        assert result is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("memory_type", "start_date", "end_date", "kwargs"),
        [
            ("on_this_day", "2015-06-17", "2024-06-17", {}),
            ("person_spotlight", "2015-01-01", "2024-06-01", {"person_names": ["Mila"]}),
        ],
        ids=["on_this_day", "multi_year_person_spotlight"],
    )
    async def test_a_yearless_title_is_kept_when_the_template_also_shows_none(
        self, memory_type, start_date, end_date, kwargs
    ):
        result = await self._titled(
            '{"title": "A lovely time together", "subtitle": null}',
            memory_type=memory_type,
            start_date=start_date,
            end_date=end_date,
            **kwargs,
        )
        assert result is not None
        assert result.title == "A lovely time together"

    @pytest.mark.asyncio
    async def test_a_holiday_title_needs_no_year_either(self):
        from immich_memories.titles.llm_titles import MemoryTitleFacts

        result = await self._titled(
            '{"title": "Noël en famille", "subtitle": null}',
            memory_type="holiday",
            start_date="2015-12-25",
            end_date="2024-12-25",
            facts=MemoryTitleFacts(holiday="christmas"),
        )
        assert result is not None
        assert result.title == "Noël en famille"

    @pytest.mark.asyncio
    async def test_the_year_may_live_in_the_subtitle(self):
        result = await self._titled(
            '{"title": "Été au bord de mer", "subtitle": "L\'été 2024"}',
            memory_type="season",
            start_date="2024-06-01",
            end_date="2024-08-31",
        )
        assert result is not None
        assert result.title == "Été au bord de mer"

    @pytest.mark.asyncio
    async def test_a_span_crossing_years_needs_both(self):
        result = await self._titled(
            '{"title": "Our year together, 2024", "subtitle": null}',
            memory_type="multi_person",
            start_date="2024-09-01",
            end_date="2025-08-31",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_a_span_crossing_years_accepts_the_short_end_form(self):
        result = await self._titled(
            '{"title": "Our year together, 2024-25", "subtitle": null}',
            memory_type="multi_person",
            start_date="2024-09-01",
            end_date="2025-08-31",
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_a_year_as_a_digit_run_inside_a_longer_number_does_not_count(self):
        """ "20245" contains the substring "2024" but does not name the year 2024."""
        result = await self._titled(
            '{"title": "Bilan de l\'annee 20245", "subtitle": null}',
            memory_type="year_in_review",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_a_trip_title_with_the_year_is_still_subject_to_the_place_guard(self):
        from immich_memories.titles.llm_titles import MemoryTitleFacts

        result = await self._titled(
            '{"title": "Nowhere in particular, 2024", "subtitle": null}',
            memory_type="trip",
            start_date="2024-06-01",
            end_date="2024-06-07",
            facts=MemoryTitleFacts(place="Crete, Greece"),
        )
        assert result is None


# A summer title, written the way each film language's catalogue would write
# "Summer 2024" (digits unchanged; only the surrounding word and script vary).
_SUMMER_WITH_YEAR_BY_LOCALE = {
    "en": "Summer 2024",
    "fr": "Été 2024",
    "nl": "Zomer 2024",
    "de": "Sommer 2024",
    "es": "Verano de 2024",
    "it": "Estate 2024",
    "pt-BR": "Verão de 2024",
    "pt-PT": "Verão de 2024",
    "pl": "Lato 2024",
    "sv": "Sommaren 2024",
    "ru": "Лето 2024",
    "ja": "2024年の夏",
    "zh-Hans": "2024年夏天",
    "ko": "2024년 여름",
}


class TestTheYearGuardReadsEveryFilmLanguage:
    """Digits are the same in every script, so the guard needs no locale table of
    its own: it reads the year straight out of whatever the catalogue would write.
    """

    @staticmethod
    def _config():
        from immich_memories.config_models_llm import LLMConfig

        return LLMConfig(
            enabled=True,
            provider="openai-compatible",
            base_url="http://localhost:8080/v1",
            model="omlx",
        )

    @staticmethod
    async def _titled(raw: str, locale: str):
        from unittest.mock import AsyncMock, patch

        from immich_memories.titles.llm_titles import generate_title_with_llm

        # WHY: replaces the reader, the only boundary these cases exercise.
        with patch(
            "immich_memories.titles.llm_titles.query_llm",
            new_callable=AsyncMock,
            return_value=raw,
        ):
            return await generate_title_with_llm(
                memory_type="season",
                locale=locale,
                start_date="2024-06-01",
                end_date="2024-08-31",
                duration_days=91,
                llm_config=TestTheYearGuardReadsEveryFilmLanguage._config(),
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("locale", sorted(_SUMMER_WITH_YEAR_BY_LOCALE))
    async def test_a_title_carrying_the_year_is_kept(self, locale):
        title = _SUMMER_WITH_YEAR_BY_LOCALE[locale]
        result = await self._titled(json.dumps({"title": title, "subtitle": None}), locale)
        assert result is not None
        assert result.title == title

    @pytest.mark.asyncio
    @pytest.mark.parametrize("locale", sorted(_SUMMER_WITH_YEAR_BY_LOCALE))
    async def test_the_same_title_without_the_year_falls_back_to_the_template(self, locale):
        title = _SUMMER_WITH_YEAR_BY_LOCALE[locale]
        yearless = (
            title.replace("2024", "")
            .replace("年の", "")
            .replace("年", "")
            .replace("년", "")
            .strip()
        )
        result = await self._titled(json.dumps({"title": yearless, "subtitle": None}), locale)
        assert result is None


class TestTheCrossYearShortFormAcceptsEveryFilmSeparator:
    """ "2024-25", "2024–25" and the ja/ko/zh wave dash/fullwidth-tilde forms
    ("2024〜25年") are all the same short form for the same two years.
    """

    @staticmethod
    def _config():
        from immich_memories.config_models_llm import LLMConfig

        return LLMConfig(
            enabled=True,
            provider="openai-compatible",
            base_url="http://localhost:8080/v1",
            model="omlx",
        )

    @staticmethod
    async def _titled(title: str, locale: str):
        from unittest.mock import AsyncMock, patch

        from immich_memories.titles.llm_titles import generate_title_with_llm

        # WHY: replaces the reader, the only boundary these cases exercise.
        with patch(
            "immich_memories.titles.llm_titles.query_llm",
            new_callable=AsyncMock,
            return_value=json.dumps({"title": title, "subtitle": None}),
        ):
            return await generate_title_with_llm(
                memory_type="season",
                locale=locale,
                start_date="2024-12-01",
                end_date="2025-02-28",
                duration_days=89,
                llm_config=TestTheCrossYearShortFormAcceptsEveryFilmSeparator._config(),
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("locale", "title"),
        [
            ("en", "Winter 2024–25"),
            ("en", "Winter 2024—25"),
            ("fr", "Hiver 2024-25"),
            ("en", "Winter 2024/25"),
            ("ja", "2024〜25年の冬"),
            ("ko", "2024~25년 겨울"),
            ("zh-Hans", "2024~25年冬天"),
        ],
        ids=["en-dash", "em-dash", "hyphen", "slash", "ja-wave-dash", "ko-tilde", "zh-tilde"],
    )
    async def test_the_short_form_is_accepted(self, locale, title):
        result = await self._titled(title, locale)
        assert result is not None
        assert result.title == title


class TestTheRequiredYearIsAFactNotARuleOfItsOwn:
    """The three prompts carry one computed fact line instead of restating the
    year rule in their own words, so prompt wording can never drift from what
    `requiring_the_year` actually checks.
    """

    @pytest.mark.asyncio
    async def test_a_span_ending_today_still_states_its_required_years(self):
        """An open-ended multi_person span is not read as needing no date."""
        from immich_memories.titles.llm_titles import MemoryTitleFacts, build_title_prompt

        today = date(2026, 9, 17)
        prompt = build_title_prompt(
            memory_type="multi_person",
            locale="fr",
            start_date="2024-02-07",
            end_date=str(today),
            duration_days=953,
            person_names=["Ada Example", "Grace Example"],
            facts=MemoryTitleFacts(today=today),
        ).text
        assert "Year(s) the title or subtitle must show: 2024 and 2026" in prompt

    @pytest.mark.asyncio
    async def test_a_titled_suggestion_naming_that_year_is_kept(self):
        from unittest.mock import AsyncMock, patch

        from immich_memories.config_models_llm import LLMConfig
        from immich_memories.titles.llm_titles import MemoryTitleFacts, generate_title_with_llm

        today = date(2026, 9, 17)
        config = LLMConfig(
            enabled=True,
            provider="openai-compatible",
            base_url="http://localhost:8080/v1",
            model="omlx",
        )
        # WHY: replaces the reader, the only boundary this case exercises.
        with patch(
            "immich_memories.titles.llm_titles.query_llm",
            new_callable=AsyncMock,
            return_value='{"title": "Ada et Grace, 2024-26", "subtitle": null}',
        ):
            result = await generate_title_with_llm(
                memory_type="multi_person",
                locale="fr",
                start_date="2024-02-07",
                end_date=str(today),
                duration_days=953,
                person_names=["Ada Example", "Grace Example"],
                facts=MemoryTitleFacts(today=today),
                llm_config=config,
            )
        assert result is not None
        assert result.title == "Ada et Grace, 2024-26"

    @pytest.mark.asyncio
    async def test_a_multi_year_spotlight_prompt_states_no_year_is_needed(self):
        from immich_memories.titles.llm_titles import build_title_prompt

        prompt = build_title_prompt(
            memory_type="person_spotlight",
            locale="en",
            start_date="2015-01-01",
            end_date="2024-06-01",
            duration_days=3440,
            person_names=["Mila"],
        ).text
        assert "Year(s) the title or subtitle must show: none" in prompt


@pytest.mark.parametrize("place,country", [("Norway", "Norway"), ("Brittany", "France")])
def test_trip_prompt_keeps_the_recorded_place_even_when_it_is_a_country(place, country):
    from immich_memories.titles.llm_titles import MemoryTitleFacts, build_title_prompt

    prompt = build_title_prompt(
        memory_type="trip",
        start_date="2030-06-01",
        end_date="2030-06-07",
        duration_days=7,
        locale="en",
        country=country,
        facts=MemoryTitleFacts(place=place),
    ).text
    assert f"Place (name it, in the title's language): {place}" in prompt
    assert "Use the region name, not the country" not in prompt
    assert "even when it is a country" in prompt
