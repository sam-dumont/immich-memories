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


def test_the_prompt_states_the_shape_in_words_for_a_server_told_without_the_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A local endpoint may be asked with no response_format; the words are the only shape then."""
    calls = _transport(monkeypatch, '{"what": ["cat"]}')

    WireAsker(LLMConfig()).ask("which?", SCHEMA, max_tokens=300)

    assert "which?" in calls[0]["prompt"]
    assert '"what"' in calls[0]["prompt"]


@pytest.mark.parametrize(
    "reply",
    [
        LLMIncompleteResponse('{"what": ["ca'),
        "not json",
        "[]",
        '```json\n{"what": ["otter"]',
        '{"what": ["otter",]}',
    ],
)
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


@pytest.mark.parametrize(
    "reply", ['{"what": "otters"}', '{"what": [3]}', "{}", '{"what": [], "extra": 1}']
)
def test_wrong_field_shapes_cannot_become_empty_votes(monkeypatch, reply):
    _transport(monkeypatch, reply)
    assert (
        WireAsker(LLMConfig(structured_output=False)).ask("otters", SCHEMA, max_tokens=300) is None
    )


@pytest.mark.parametrize(
    "reply", ['```json\n{"what": ["otters"]}\n```', 'The answer is {"what": ["otters"]}']
)
def test_complete_fenced_or_prefaced_json_keeps_its_subject(monkeypatch, reply):
    _transport(monkeypatch, reply)
    assert WireAsker(LLMConfig()).ask("otters", SCHEMA, max_tokens=300) == {"what": ["otters"]}


def test_one_complete_object_with_surrounding_prose_is_still_valid(monkeypatch):
    _transport(monkeypatch, 'Here is the answer: {"what": ["otters"]}. Those are the subjects.')
    assert WireAsker(LLMConfig()).ask("otters", SCHEMA, max_tokens=300) == {"what": ["otters"]}


def test_large_offered_name_lists_are_not_restricted_to_the_owners_words(monkeypatch):
    calls = _transport(monkeypatch, '{"choices": ["option 55"]}')
    schema = reading.object_schema(
        choices={
            "type": "array",
            "items": {"type": "string", "enum": [f"option {i}" for i in range(60)]},
        }
    )
    answer = WireAsker(LLMConfig(structured_output=False)).ask(
        "Choose an alternate name from the offered options.", schema, max_tokens=300
    )
    assert answer == {"choices": ["option 55"]}
    assert "owner_request" not in calls[0]["prompt"]
    assert '"type": "array"' in calls[0]["prompt"]
