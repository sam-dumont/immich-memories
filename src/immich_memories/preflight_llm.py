"""Preflight checks for the LLM and reader endpoints."""

from __future__ import annotations

import logging

import httpx

from immich_memories.analysis.llm_providers import ANTHROPIC_VERSION, resolved_llm_config
from immich_memories.analysis.provider_health import (
    ProviderHealth,
    ProviderState,
    classify_provider_response,
)
from immich_memories.config import Config
from immich_memories.preflight import CheckResult, CheckStatus

logger = logging.getLogger(__name__)

_UNREACHABLE = "Check the configured LLM base URL and provider availability"


def _transport_failure(exc: Exception, unreachable: str = _UNREACHABLE) -> CheckResult:
    """One answer for every way a provider can fail to answer at all."""
    if isinstance(exc, httpx.ReadTimeout):
        return CheckResult(
            name="LLM",
            status=CheckStatus.WARNING,
            message="Reader is slow to answer",
            details="Increase llm.preflight_timeout_seconds for a busy reader and retry",
        )
    if isinstance(exc, httpx.ConnectError):
        return CheckResult(
            name="LLM", status=CheckStatus.WARNING, message="Cannot connect", details=unreachable
        )
    return CheckResult(
        name="LLM",
        status=CheckStatus.WARNING,
        message="Connection error",
        details=type(exc).__name__,
    )


def _check_ollama(base_url: str, model: str, timeout: float) -> CheckResult:
    """Check Ollama server availability via /api/tags.

    Args:
        base_url: Ollama server URL.
        model: Configured model name.

    Returns:
        CheckResult with status and details.
    """
    try:
        normalized = base_url.rstrip("/")

        with httpx.Client(timeout=timeout) as client:
            response = client.get(f"{normalized}/api/tags")
            response.raise_for_status()
            data = response.json()

            models = data.get("models", [])
            model_names = [m.get("name", "") for m in models]

            if model and model not in model_names:
                base_name = model.split(":")[0]
                if not any(m.startswith(base_name) for m in model_names):
                    return CheckResult(
                        name="LLM",
                        status=CheckStatus.WARNING,
                        message=f"Connected but missing model: {model}",
                        details=f"Available: {', '.join(model_names[:5])}{'...' if len(model_names) > 5 else ''}",
                    )

            return CheckResult(
                name="LLM",
                status=CheckStatus.OK,
                message=f"Connected (ollama, {len(models)} models)",
                details=f"Model: {model}",
            )

    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError, OSError) as exc:
        return _transport_failure(
            exc, "Check the configured LLM base URL and that Ollama is running"
        )


def _llm_health_failure(
    health: ProviderHealth,
    model: str,
    route: str = "Chat-completions",
    path: str = "/chat/completions",
) -> CheckResult | None:
    """Translate provider health into a safe, actionable preflight failure."""
    if health.state is ProviderState.AUTH_FAILED:
        return CheckResult(
            name="LLM",
            status=CheckStatus.ERROR,
            message="Authentication failed",
            details="The configured API key was rejected",
        )
    if health.state is ProviderState.MODEL_MISSING:
        return CheckResult(
            name="LLM",
            status=CheckStatus.WARNING,
            message=f"Configured model unavailable: {model}",
            details=f"Model: {model}",
        )
    if health.state is ProviderState.ROUTE_MISSING:
        return CheckResult(
            name="LLM",
            status=CheckStatus.WARNING,
            message=f"{route} route unavailable",
            details=f"Check that the configured base URL exposes {path}",
        )
    if health.available:
        return None
    return CheckResult(
        name="LLM",
        status=CheckStatus.WARNING,
        message=health.message,
        details="Check the configured LLM provider",
    )


def _check_openai_compatible(
    base_url: str, model: str, api_key: str, timeout: float
) -> CheckResult:
    """Check OpenAI-compatible server via test completion.

    Args:
        base_url: API base URL (e.g. http://localhost:8080/v1).
        model: Model name.
        api_key: API key (may be empty for local servers).

    Returns:
        CheckResult with status and details.
    """
    try:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        with httpx.Client(timeout=timeout, headers=headers) as client:
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1,
            }
            response = client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                json=payload,
            )

            try:
                response_body = response.json()
            except ValueError:
                response_body = {}
            health = classify_provider_response(response.status_code, response_body, model)
            if failure := _llm_health_failure(health, model):
                return failure

            return CheckResult(
                name="LLM",
                status=CheckStatus.OK,
                message="Connected (openai-compatible)",
                details=f"Model: {model}",
            )

    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError, OSError) as exc:
        return _transport_failure(exc)


def _anthropic_headers(api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "anthropic-version": ANTHROPIC_VERSION}
    if api_key:
        headers["x-api-key"] = api_key
    return headers


def _listed_model_ids(client: httpx.Client, base_url: str) -> list[str] | None:
    """The model ids the host publishes, or None when it publishes none.

    Anthropic and z.ai's compatible route both answer `GET /v1/models` with
    `{"data": [{"id": ...}]}` (measured 2026-09-14). A host behind a gateway
    that serves only `/v1/messages` answers something else, and then the probe
    below is the only way to know it is there.
    """
    try:
        response = client.get(f"{base_url}/v1/models")
        if response.status_code != 200:
            return None
        data = response.json().get("data")
    except ValueError:
        return None
    if not isinstance(data, list):
        return None
    return [str(entry["id"]) for entry in data if isinstance(entry, dict) and "id" in entry]


def _catalogue_result(listed: list[str], model: str) -> CheckResult:
    if model and model not in listed:
        shown = ", ".join(listed[:5])
        return CheckResult(
            name="LLM",
            status=CheckStatus.WARNING,
            message=f"Connected but missing model: {model}",
            details=f"Available: {shown}{'...' if len(listed) > 5 else ''}",
        )
    return CheckResult(
        name="LLM",
        status=CheckStatus.OK,
        message=f"Connected (anthropic, {len(listed)} models)",
        details=f"Model: {model}",
    )


def _one_token_probe(client: httpx.Client, base_url: str, model: str) -> CheckResult:
    """Ask the host for a single token, which is the cheapest proof it answers."""
    response = client.post(
        f"{base_url}/v1/messages",
        json={"model": model, "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]},
    )
    try:
        body = response.json()
    except ValueError:
        body = {}
    health = classify_provider_response(response.status_code, body, model)
    failure = _llm_health_failure(health, model, "Messages", "/v1/messages")
    return failure or CheckResult(
        name="LLM",
        status=CheckStatus.OK,
        message="Connected (anthropic)",
        details=f"Model: {model}",
    )


def _check_anthropic(base_url: str, model: str, api_key: str, timeout: float) -> CheckResult:
    """Check a Messages API host: its model list where it has one, a probe where it does not."""
    normalized = base_url.rstrip("/")
    try:
        with httpx.Client(timeout=timeout, headers=_anthropic_headers(api_key)) as client:
            listed = _listed_model_ids(client, normalized)
            if listed:
                return _catalogue_result(listed, model)
            return _one_token_probe(client, normalized, model)
    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError, OSError) as exc:
        return _transport_failure(exc)


def _reader_settings_chosen(config: Config) -> list[str]:
    """Reader settings someone set, leaving out a key that only came from the shell.

    `OPENAI_API_KEY` is exported for many tools; finding it is not choosing a reader.
    """
    from immich_memories.config_loader import env_alias_overrides

    from_shell = "llm.api_key" in env_alias_overrides(config)
    return [name for name in config.llm.configured_fields if not (from_shell and name == "api_key")]


def check_llm(config: Config) -> CheckResult:
    """Check LLM provider availability.

    Dispatches on the resolved provider:
    - "ollama": GET /api/tags
    - "anthropic": GET /v1/models, or a one-token POST /v1/messages
    - "openai-compatible": POST /chat/completions with minimal payload

    Args:
        config: Configuration to use.

    Returns:
        CheckResult with status and details.
    """
    if not config.llm.enabled:
        if chosen := _reader_settings_chosen(config):
            return CheckResult(
                name="LLM",
                status=CheckStatus.WARNING,
                message="Reader configured but disabled",
                details=(
                    f"Set: {', '.join(chosen)}. "
                    "Set advanced.llm.enabled: true to allow local or remote reader calls"
                ),
            )
        return CheckResult(name="LLM", status=CheckStatus.SKIPPED, message="LLM disabled")
    try:
        reader = config.editorial.resolve_reader(config.llm.model)
    except ValueError as exc:
        return CheckResult(name="LLM", status=CheckStatus.ERROR, message=str(exc))
    if reader == "rules" and not config.llm.model.strip():
        return CheckResult(
            name="LLM", status=CheckStatus.SKIPPED, message="No LLM configured for text features"
        )
    # A named provider is its adapter plus a URL, and the check has to reach
    # the endpoint the run will: `zai` and `openai` both resolve to one of the
    # two adapters, and to the vendor URL where none was set.
    llm = resolved_llm_config(config.llm)
    if llm.runs_locally:
        from immich_memories.local_inference import local_reader_files

        try:
            local_reader_files(llm)
        except (OSError, RuntimeError) as exc:
            return CheckResult(name="LLM", status=CheckStatus.ERROR, message=str(exc))
        return CheckResult(
            name="LLM",
            status=CheckStatus.OK,
            message="Local reader installed; generation not tested",
            details="The app starts llama.cpp when a request needs it",
        )
    base_url = llm.base_url
    model = llm.model

    if not base_url:
        return CheckResult(
            name="LLM",
            status=CheckStatus.SKIPPED,
            message="Not configured",
            details="No base_url set",
        )

    if llm.provider == "ollama":
        return _check_ollama(base_url, model, llm.preflight_timeout_seconds)
    if llm.provider == "anthropic":
        return _check_anthropic(base_url, model, llm.api_key, llm.preflight_timeout_seconds)
    return _check_openai_compatible(base_url, model, llm.api_key, llm.preflight_timeout_seconds)
