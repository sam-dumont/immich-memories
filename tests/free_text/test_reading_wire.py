"""The free-text reader's questions go through the product's own LLM transport."""

from __future__ import annotations

from typing import Any

import pytest

from immich_memories.analysis.llm_wire import LLMIncompleteResponse
from immich_memories.config_models_llm import LLMConfig
from immich_memories.free_text import reading
from immich_memories.free_text.reading import WireAsker

SCHEMA = reading.object_schema(what={"type": "array", "items": {"type": "string"}})


def _transport(monkeypatch: pytest.MonkeyPatch, reply: str | Exception) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def query(prompt: str, config: LLMConfig, **options: Any) -> str:
        calls.append({"prompt": prompt, **options})
        if isinstance(reply, Exception):
            raise reply
        return reply

    # WHY: replaces the HTTP call to the configured model server.
    monkeypatch.setattr(reading, "query_llm", query)
    return calls


def test_an_answer_comes_back_in_the_shape_the_server_was_told_to_keep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _transport(monkeypatch, '{"what": ["cat"]}')

    answer = WireAsker(LLMConfig()).ask("which?", SCHEMA, max_tokens=300)

    assert answer == {"what": ["cat"]}
    assert calls[0]["require_complete"] is True
    assert calls[0]["response_format"]["json_schema"]["schema"] == SCHEMA


@pytest.mark.parametrize("reply", [LLMIncompleteResponse('{"what": ["ca'), "not json", "[]"])
def test_a_cut_off_or_unreadable_answer_is_none(
    monkeypatch: pytest.MonkeyPatch, reply: str | Exception
) -> None:
    _transport(monkeypatch, reply)

    assert WireAsker(LLMConfig()).ask("which?", SCHEMA, max_tokens=300) is None


def test_a_question_asked_from_inside_a_running_event_loop_is_answered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    _transport(monkeypatch, '{"what": ["cat"]}')

    async def from_a_loop() -> Any:
        return WireAsker(LLMConfig()).ask("which?", SCHEMA, max_tokens=300)

    assert asyncio.run(from_a_loop()) == {"what": ["cat"]}
