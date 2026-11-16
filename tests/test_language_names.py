"""The title prompt names the film's language once per supported locale, and no other."""

from __future__ import annotations

from immich_memories.i18n import LANGUAGE_NAMES, SUPPORTED_LOCALES
from immich_memories.titles.llm_titles import build_title_prompt


def test_every_supported_locale_has_a_language_name_and_nothing_else_does() -> None:
    assert set(LANGUAGE_NAMES) == set(SUPPORTED_LOCALES)
    assert all(name.strip() for name in LANGUAGE_NAMES.values())


def test_the_title_prompt_asks_for_the_locales_language() -> None:
    prompt = build_title_prompt("trip", "pt-BR", "2024-06-01", "2024-06-05", 5)

    assert "Brazilian Portuguese" in prompt.text
