"""A prose seat asks for its JSON shape and states its own sampling; a server that refuses either is still answered.

Whether the shape is asked for at all now depends on where the server lives: measured
2026-09-29, oMLX's grammar-constrained decoder stalled forever on the episode-reading
schema, so a server on this machine or this private network defaults to no shape and a
hosted one keeps asking for it. An explicit `structured_output` always wins either way.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from immich_memories.analysis.llm_text_identity import text_model_identity
from immich_memories.config_models_llm import LLMConfig
from tests.test_llm_query import _openai_400, _openai_response

SHAPE = {
    "type": "json_schema",
    "json_schema": {
        "name": "title",
        "schema": {"type": "object", "properties": {"title": {"type": "string"}}},
    },
}


def _local(**overrides) -> LLMConfig:
    return LLMConfig(
        provider="openai-compatible",
        base_url="http://localhost:9999/v1",
        model="small",
        **overrides,
    )


def _hosted(**overrides) -> LLMConfig:
    return LLMConfig(
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="gpt",
        **overrides,
    )


async def _sent(config, **options):
    from immich_memories.analysis.llm_query import query_llm

    # WHY: the LLM server is the external boundary this request reaches.
    with patch("httpx.AsyncClient.post", return_value=_openai_response()) as post:
        await query_llm("Name this film", config, **options)
    return post.call_args[1]["json"]


@pytest.mark.asyncio
async def test_a_hosted_seat_s_json_shape_reaches_the_server():
    body = await _sent(_hosted(), response_format=SHAPE)

    assert body["response_format"] == SHAPE


@pytest.mark.asyncio
async def test_a_local_server_gets_no_shape_left_at_its_default():
    body = await _sent(_local(), response_format=SHAPE)

    assert "response_format" not in body


@pytest.mark.asyncio
async def test_an_explicit_true_wins_on_a_local_server():
    body = await _sent(_local(structured_output=True), response_format=SHAPE)

    assert body["response_format"] == SHAPE


@pytest.mark.asyncio
async def test_an_explicit_false_wins_on_a_hosted_server():
    body = await _sent(_hosted(structured_output=False), response_format=SHAPE)

    assert "response_format" not in body


@pytest.mark.asyncio
async def test_structured_output_off_sends_no_shape():
    body = await _sent(_local(structured_output=False), response_format=SHAPE)

    assert "response_format" not in body


@pytest.mark.asyncio
async def test_a_local_server_is_told_the_repetition_penalty_rather_than_left_to_its_default():
    body = await _sent(_local())

    assert body["repetition_penalty"] == 1.0


@pytest.mark.asyncio
async def test_a_hosted_openai_endpoint_gets_no_repetition_penalty():
    body = await _sent(_hosted())

    assert "repetition_penalty" not in body


@pytest.mark.asyncio
async def test_a_server_that_refuses_the_shape_is_asked_again_without_it_and_remembers():
    from immich_memories.analysis.llm_query import query_llm

    answers = iter(
        [
            _openai_400("response_format is not supported by this server"),
            _openai_response(),
            _openai_response(),
        ]
    )
    sent = []

    def server(url, json):
        sent.append(dict(json))
        return next(answers)

    config = _local(structured_output=True)
    # WHY: the LLM server is the external boundary this request reaches.
    with patch("httpx.AsyncClient.post", side_effect=server):
        await query_llm("Name this film", config, response_format=SHAPE)
        await query_llm("Name this film again", config, response_format=SHAPE)

    first, retry, later = sent
    assert "response_format" in first
    assert "response_format" not in retry
    assert "response_format" not in later
    assert '"properties"' in retry["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_a_server_that_refuses_the_penalty_is_asked_again_without_it():
    from immich_memories.analysis.llm_query import query_llm

    refused = _openai_400("Unrecognized request argument supplied: repetition_penalty")
    # WHY: the LLM server is the external boundary this request reaches.
    with patch("httpx.AsyncClient.post", side_effect=[refused, _openai_response()]) as post:
        await query_llm("Name this film", _local())

    assert "repetition_penalty" not in post.call_args_list[1][1]["json"]


@pytest.mark.asyncio
async def test_ollama_gets_the_shape_as_its_format_and_the_penalty_as_an_option():
    from unittest.mock import AsyncMock, MagicMock

    from immich_memories.analysis.llm_query import query_llm

    config = LLMConfig(
        provider="ollama",
        base_url="http://localhost:11434",
        model="small",
        structured_output=True,
    )
    answer = AsyncMock(status_code=200, json=MagicMock(return_value={"response": "{}"}))
    answer.raise_for_status = lambda: None
    # WHY: the LLM server is the external boundary this request reaches.
    with patch("httpx.AsyncClient.post", return_value=answer) as post:
        await query_llm("Name this film", config, response_format=SHAPE)
    body = post.call_args[1]["json"]

    assert body["format"] == SHAPE["json_schema"]["schema"]
    assert body["options"]["repeat_penalty"] == 1.0


@pytest.mark.asyncio
async def test_ollama_on_a_local_server_defaults_to_no_shape():
    from unittest.mock import AsyncMock, MagicMock

    from immich_memories.analysis.llm_query import query_llm

    config = LLMConfig(provider="ollama", base_url="http://localhost:11434", model="small")
    answer = AsyncMock(status_code=200, json=MagicMock(return_value={"response": "{}"}))
    answer.raise_for_status = lambda: None
    # WHY: the LLM server is the external boundary this request reaches.
    with patch("httpx.AsyncClient.post", return_value=answer) as post:
        await query_llm("Name this film", config, response_format=SHAPE)
    body = post.call_args[1]["json"]

    assert "format" not in body


def test_changing_either_setting_is_another_model_identity():
    base = text_model_identity(_local(structured_output=True), thinking=False)

    assert text_model_identity(_local(structured_output=False), thinking=False) != base
    assert (
        text_model_identity(_local(structured_output=True, repetition_penalty=1.1), thinking=False)
        != base
    )


def test_left_at_its_default_a_local_and_a_hosted_endpoint_carry_different_identities():
    """Same unset setting, different resolved behaviour: the identity must tell them apart."""
    local = text_model_identity(_local(), thinking=False)
    hosted = text_model_identity(_hosted(), thinking=False)

    assert local != hosted


@pytest.mark.asyncio
async def test_schema_capability_refusal_retries_as_json_object_and_remembers(caplog):
    import copy
    import logging

    from immich_memories.analysis.llm_query import query_llm

    answers = iter(
        [
            _openai_400("model_not_capable: does not support JSON schema mode, use json_object"),
            _openai_response(),
            _openai_response(),
            _openai_response(),
        ]
    )
    sent = []

    def server(_url, json):
        sent.append(copy.deepcopy(json))
        return next(answers)

    config = _hosted()
    # WHY: simulate the provider's capability refusal at the HTTP boundary.
    with caplog.at_level(logging.INFO), patch("httpx.AsyncClient.post", side_effect=server):
        assert await query_llm("Name this film", config, response_format=SHAPE) == '{"ok": true}'
        await query_llm("Name it again", config, response_format=SHAPE)
        await query_llm(
            "Another model", config.model_copy(update={"model": "other"}), response_format=SHAPE
        )
    assert [p["response_format"] for p in sent] == [
        SHAPE,
        {"type": "json_object"},
        {"type": "json_object"},
        SHAPE,
    ]
    assert '"properties"' in sent[1]["messages"][-1]["content"]
    assert '"title"' in sent[2]["messages"][-1]["content"]
    assert caplog.text.count("adapting request (json_object)") == 1


@pytest.mark.asyncio
async def test_invalid_schema_is_not_retried_as_a_capability_problem():
    import httpx

    from immich_memories.analysis.llm_query import query_llm

    refused = _openai_400("Invalid json_schema: required must include every property")
    # WHY: malformed input is a provider error, not a missing capability.
    with (
        patch("httpx.AsyncClient.post", return_value=refused) as post,
        pytest.raises(httpx.HTTPStatusError),
    ):
        await query_llm("Name this film", _hosted(), response_format=SHAPE)
    assert post.call_count == 1


@pytest.mark.asyncio
async def test_concurrent_schema_refusals_announce_the_learned_capability_once(caplog):
    import asyncio
    import logging

    from immich_memories.analysis.llm_query import query_llm

    ready = asyncio.Event()
    initial = 0

    async def server(_url, json):
        nonlocal initial
        if json.get("response_format", {}).get("type") == "json_schema":
            initial += 1
            if initial == 2:
                ready.set()
            await ready.wait()
            return _openai_400("JSON schema is unsupported; use json_object")
        return _openai_response()

    # WHY: both concurrent requests reach the provider before either learns its capability.
    with caplog.at_level(logging.INFO), patch("httpx.AsyncClient.post", side_effect=server):
        await asyncio.gather(
            *(query_llm(prompt, _hosted(), response_format=SHAPE) for prompt in ("First", "Second"))
        )
    assert initial == 2
    assert caplog.text.count("adapting request (json_object)") == 1
