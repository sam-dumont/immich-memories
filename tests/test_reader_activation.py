"""The configured reader needs consent and keeps one endpoint across its callers."""

import pytest

from immich_memories.analysis.llm_providers import (
    batch_route_for,
    reader_concurrency,
    resolved_llm_config,
)
from immich_memories.config import Config
from immich_memories.config_models_llm import LLMConfig
from immich_memories.preflight import CheckStatus
from immich_memories.preflight_llm import check_llm


@pytest.mark.parametrize(
    ("provider", "url", "dialect"),
    [
        ("openai", "https://api.openai.com/v1", "openai-compatible"),
        ("anthropic", "https://api.anthropic.com", "anthropic"),
        ("zai", "https://api.z.ai/api/anthropic", "anthropic"),
    ],
)
def test_named_provider_without_url_uses_its_host(provider, url, dialect):
    config = LLMConfig(enabled=True, provider=provider, model="hosted-model")
    resolved = resolved_llm_config(config)
    assert resolved.base_url == url
    assert resolved.provider == dialect
    assert not config.runs_locally
    assert reader_concurrency(config) == 4
    assert batch_route_for(config) is not None


def test_switching_named_provider_does_not_keep_the_previous_default_url():
    config = LLMConfig(enabled=True, provider="openai", model="model")
    assert resolved_llm_config(config).base_url == "https://api.openai.com/v1"
    config.provider = "anthropic"
    assert resolved_llm_config(config).base_url == "https://api.anthropic.com"


@pytest.mark.parametrize(
    "settings", [{"model": "my-model"}, {"base_url": "http://localhost:8000/v1"}]
)
def test_configured_reader_stays_disabled_until_enabled(settings):
    config = Config(llm=settings)
    assert not config.llm.enabled
    result = check_llm(config)
    assert result.status is CheckStatus.WARNING
    assert result.message == "Reader configured but disabled"


def test_round_tripping_default_config_does_not_warn_about_a_reader():
    config = Config.model_validate(Config().model_dump())
    assert check_llm(config).status is CheckStatus.SKIPPED


def test_environment_provider_override_uses_the_selected_host(monkeypatch, tmp_path):
    monkeypatch.setenv("IMMICH_MEMORIES_LLM__ENABLED", "true")
    monkeypatch.setenv("IMMICH_MEMORIES_LLM__PROVIDER", "zai")
    path = tmp_path / "config.yaml"
    path.write_text("advanced:\n  llm:\n    provider: openai\n")
    config = Config.from_yaml(path, stored={})
    assert resolved_llm_config(config.llm).base_url == "https://api.z.ai/api/anthropic"


@pytest.mark.parametrize("provider", ["openai-compatible", "ollama"])
def test_blank_generic_endpoint_still_owns_the_local_reader(provider):
    config = LLMConfig(enabled=True, provider=provider)
    assert config.runs_locally
    assert resolved_llm_config(config).base_url == ""
    assert reader_concurrency(config) == 1
    assert batch_route_for(config) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "url"),
    [
        ("openai", "https://api.openai.com/v1/chat/completions"),
        ("anthropic", "https://api.anthropic.com/v1/messages"),
        ("zai", "https://api.z.ai/api/anthropic/v1/messages"),
    ],
)
async def test_named_provider_reaches_its_real_adapter_without_an_explicit_url(
    monkeypatch, provider, url
):
    import json

    import httpx

    from immich_memories.analysis.llm_query import query_llm

    seen = []

    def answer(request):
        seen.append(request)
        if provider == "openai":
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": '{"ok":true}'}, "finish_reason": "stop"}]
                },
            )
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": '{"ok":true}'}], "stop_reason": "end_turn"},
        )

    client_type = httpx.AsyncClient
    # WHY: vendor HTTP is the boundary; the real adapter still serializes and parses the request.
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(answer), **kwargs),
    )
    config = LLMConfig(enabled=True, provider=provider, model="reader", thinking="auto")
    response_format = {
        "type": "json_schema",
        "json_schema": {"name": "episode_reading", "schema": {"type": "object"}},
    }
    assert (
        await query_llm("Read this episode", config, response_format=response_format)
        == '{"ok":true}'
    )
    assert str(seen[0].url) == url
    payload = json.loads(seen[0].content)
    assert "repetition_penalty" not in payload
    if provider == "openai":
        assert payload["response_format"] == response_format
    else:
        assert "thinking" not in payload


def test_preflight_named_provider_checks_host_instead_of_local_install(monkeypatch):
    import httpx

    seen = []

    def answer(request):
        seen.append(request)
        return httpx.Response(200, json={"data": [{"id": "reader"}]})

    client_type = httpx.Client
    # WHY: vendor HTTP is the boundary; preflight must probe the effective hosted route.
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: client_type(transport=httpx.MockTransport(answer), **kwargs),
    )
    config = Config(llm={"enabled": True, "provider": "anthropic", "model": "reader"})
    assert check_llm(config).status is CheckStatus.OK
    assert str(seen[0].url) == "https://api.anthropic.com/v1/models"
