"""An `--ask` film's title, in the film's language (#2064).

The pool's name is the raw request ("landscapes, no humans"); it must never reach
the screen as-is. The subject rides as an occasion fact through the same path every
other route's title takes (`resolve_film_title` -> `generate_title_with_llm` ->
`_guarded_suggestion`), so the same guards apply, and the fallback -- no model
(BASIC), or a refused suggestion -- is the dated template in the film's language,
built by the existing title template helpers, never the request text itself.
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
from immich_memories.titles.film_title import resolve_film_title
from immich_memories.titles.llm_titles import MemoryTitleFacts, generate_title_with_llm
from immich_memories.titles.text_builder import generate_title, infer_selection_type
from tests.conftest import make_clip

# A synthetic ask subject, in English (what captions name things). It must never be
# the on-screen title, in any locale.
_RAW_REQUEST = "landscapes, no humans"
_RANGE = DateRange(start=datetime(2024, 6, 1), end=datetime(2024, 8, 31))

# Distinctive English words, chosen to avoid the short articles ("a", "de", "in")
# that are also real words in Romance languages -- used only to show a non-English
# fallback title did not pick any of them up. The production catalogue (`i18n.py`,
# `text_builder.py`) is the thing actually tested for correctness, not re-derived here.
_ENGLISH_STOPWORDS = frozenset({"the", "and", "landscapes", "humans", "summer"})


def _llm_config() -> LLMConfig:
    return LLMConfig(
        enabled=True,
        provider="openai-compatible",
        base_url="http://localhost:8080/v1",
        model="omlx",
    )


def _config_with_llm() -> Config:
    return Config(
        tier="full", llm={"enabled": True, "base_url": "http://llm.test/v1", "model": "omlx"}
    )


async def _ask_titled(raw: str | Exception, *, locale: str) -> object:
    """Stand in for the reader at the same boundary `generate_title_with_llm` queries."""
    # WHY: query_llm is the only external boundary `generate_title_with_llm` crosses.
    with patch(
        "immich_memories.titles.llm_titles.query_llm",
        new_callable=AsyncMock,
        side_effect=raw if isinstance(raw, Exception) else None,
        return_value=None if isinstance(raw, Exception) else raw,
    ):
        return await generate_title_with_llm(
            memory_type="album",
            locale=locale,
            start_date="2024-06-01",
            end_date="2024-08-31",
            duration_days=91,
            facts=MemoryTitleFacts(occasion_name=_RAW_REQUEST),
            llm_config=_llm_config(),
        )


@pytest.mark.asyncio
async def test_a_french_ask_title_falls_back_to_the_template_on_model_refusal() -> None:
    """A model answer that adds nothing over the template's own year is refused
    (#2063's guards); the run then shows the dated template, never the raw request."""
    result = await _ask_titled(json.dumps({"title": "2024", "subtitle": None}), locale="fr")

    assert result is None


@pytest.mark.asyncio
async def test_an_english_ask_title_is_kept_in_english() -> None:
    result = await _ask_titled(
        json.dumps({"title": "Open country, no faces, 2024", "subtitle": None}), locale="en"
    )

    assert result is not None
    assert result.title == "Open country, no faces, 2024"
    assert _RAW_REQUEST not in result.title


@pytest.mark.asyncio
async def test_a_guard_passing_french_title_is_kept_verbatim() -> None:
    result = await _ask_titled(
        json.dumps({"title": "Paysages sans personne, 2024", "subtitle": None}), locale="fr"
    )

    assert result is not None
    assert result.title == "Paysages sans personne, 2024"
    assert _RAW_REQUEST not in result.title


def test_basic_tier_with_no_model_falls_back_to_the_template(caplog) -> None:
    """BASIC (no configured reader): the run asks for nothing and the template names
    the memory instead -- the raw request never reaches `title_override`."""
    called = []

    title, _subtitle, source = resolve_film_title(
        enabled=None,
        title_override=None,
        clips=[make_clip("clip-1")],
        config=Config(tier="nas"),
        memory_type="album",
        date_range=_RANGE,
        person_names=[],
        memory_preset_params={"subject": _RAW_REQUEST},
        ask=lambda **kwargs: called.append(kwargs),
    )

    assert title is None
    assert source is None
    assert called == []


@pytest.mark.parametrize("locale", sorted(SUPPORTED_LOCALES))
def test_the_template_fallback_is_never_the_raw_request_in_any_locale(locale: str) -> None:
    """The dated template every ask film falls back to, built by the same helper the
    renderer uses, for every film language the app ships."""
    selection_type = infer_selection_type(
        start_date=_RANGE.start.date(), end_date=_RANGE.end.date(), memory_type="album"
    )
    info = generate_title(
        selection_type, start_date=_RANGE.start.date(), end_date=_RANGE.end.date(), locale=locale
    )

    assert _RAW_REQUEST not in info.main_title
    assert "landscapes" not in info.main_title.casefold()
    if locale != "en":
        words = set(info.main_title.casefold().replace("-", " ").split())
        assert not words & _ENGLISH_STOPWORDS
