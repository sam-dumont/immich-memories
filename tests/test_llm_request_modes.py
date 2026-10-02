"""One local reader can enforce small answers without constraining episode readings."""

from unittest.mock import patch

import httpx
import pytest

from immich_memories.config_models_llm import LLMConfig
from immich_memories.free_text.reading import WireAsker, object_schema


def test_local_free_text_keeps_its_required_json_contract():
    config = LLMConfig(
        enabled=True,
        provider="openai-compatible",
        base_url="http://localhost:9999/v1",
        model="small",
    )
    sent = []

    async def server(url, **options):
        body = options["json"]
        sent.append(body)
        answer = '{"what": ["cat"]}'
        if "response_format" not in body:
            answer = f"```json\n{answer}\n```"
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"choices": [{"message": {"content": answer}, "finish_reason": "stop"}]},
        )

    # WHY: emulate the external server; all reader and transport code runs unchanged.
    with patch("httpx.AsyncClient.post", side_effect=server):
        answer = WireAsker(config).ask(
            "Which animals?",
            object_schema(what={"type": "array", "items": {"type": "string"}}),
            max_tokens=300,
        )

    assert answer == {"what": ["cat"]}
    assert sent[0]["response_format"]["type"] == "json_schema"


def test_request_specific_policy_cannot_reuse_a_force_all_schemas_producer():
    from immich_memories.analysis.editorial_text_gateway import semantic_text_model_identity

    config = LLMConfig(
        enabled=True,
        provider="openai-compatible",
        base_url="http://localhost:9999/v1",
        model="small",
    )
    automatic = semantic_text_model_identity(config, thinking=False)
    force_all = semantic_text_model_identity(
        config.model_copy(update={"structured_output": True}), thinking=False
    )

    assert automatic != force_all


@pytest.mark.parametrize("provider", ["openai-compatible", "ollama"])
@pytest.mark.parametrize("override", [None, True, False])
@pytest.mark.asyncio
async def test_one_endpoint_switches_modes_by_request_kind(provider, override):
    from immich_memories.analysis.llm_query import query_llm
    from immich_memories.analysis.prose_shapes import episode_reading_shape, title_shape

    config = LLMConfig(
        enabled=True,
        provider=provider,
        base_url="http://localhost:9999/v1",
        model="small",
        structured_output=override,
    )
    sent = []

    async def server(url, **options):
        sent.append(options["json"])
        reply = (
            {"response": "{}", "done": True}
            if provider == "ollama"
            else {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}
        )
        return httpx.Response(200, request=httpx.Request("POST", url), json=reply)

    shapes = [title_shape(trip=True), episode_reading_shape(1, lean=False), title_shape(trip=False)]
    # WHY: capture the external provider payloads without replacing mode selection or parsing.
    with patch("httpx.AsyncClient.post", side_effect=server):
        for shape in shapes:
            assert await query_llm("Return JSON", config, response_format=shape) == "{}"

    field = "format" if provider == "ollama" else "response_format"
    expected = [True, False, True] if override is None else [override] * 3
    assert [field in body for body in sent] == expected
    for shape, body, enforced in zip(shapes, sent, expected, strict=True):
        if enforced:
            assert body[field] == (
                shape["json_schema"]["schema"] if provider == "ollama" else shape
            )


@pytest.mark.asyncio
async def test_cached_answers_stay_with_their_request_mode():
    from immich_memories.analysis.llm_query import query_llm
    from immich_memories.analysis.prose_shapes import episode_reading_shape, title_shape
    from tests.annotation_rows import annotation_store

    config = LLMConfig(
        enabled=True,
        provider="openai-compatible",
        base_url="http://localhost:9999/v1",
        model="small",
    )
    sent = []

    async def server(url, **options):
        constrained = "response_format" in options["json"]
        sent.append(constrained)
        answer = '{"mode":"strict"}' if constrained else '{"mode":"prompt"}'
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"choices": [{"message": {"content": answer}, "finish_reason": "stop"}]},
        )

    store = annotation_store()
    shapes = [
        title_shape(trip=False),
        episode_reading_shape(1, lean=False),
        title_shape(trip=False),
    ]
    # WHY: the HTTP server is external; the real scratch-store judgment cache handles reuse.
    with patch("httpx.AsyncClient.post", side_effect=server):
        answers = [
            await query_llm("Same words", config, judgments=store, response_format=shape)
            for shape in shapes
        ]
    assert answers == ['{"mode":"strict"}', '{"mode":"prompt"}', '{"mode":"strict"}']
    assert sent == [True, False]


@pytest.mark.parametrize(
    ("provider", "endpoint", "model", "override", "banked_identity"),
    [
        ("openai", "https://api.openai.com/v1", "gpt", None, "gpt@text-1c5a4ef763333d2ed58e"),
        (
            "openai-compatible",
            "http://localhost:9999/v1",
            "small",
            True,
            "small@text-64bf26bdf9e34da9fd96",
        ),
        (
            "openai-compatible",
            "http://localhost:9999/v1",
            "small",
            False,
            "small@text-fe51037e35bac7f942c5",
        ),
    ],
)
def test_unchanged_modes_keep_their_existing_banked_answers(
    provider, endpoint, model, override, banked_identity
):
    from immich_memories.analysis.editorial_text_gateway import semantic_text_model_identity

    config = LLMConfig(
        enabled=True, provider=provider, base_url=endpoint, model=model, structured_output=override
    )
    # Persisted producer identities measured on main 9ab1bf52, before request-specific selection.
    assert semantic_text_model_identity(config, thinking=False) == banked_identity
