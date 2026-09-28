"""Secrets supplied by the environment: the shortcut variables and `${VAR}` in config.yaml.

Docker and Kubernetes users keep the Immich API key out of the config file and supply
it through the environment, either as `${VAR}` inside the YAML or as `IMMICH_API_KEY`.
The app never writes config.yaml (#871), so these tests cover the read side: every
variable reaches its field, and never another provider's.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from immich_memories.config_loader import Config, _apply_env_overrides

FROM_ENV = "sk-do-not-write-me-to-disk"


def test_the_ace_step_key_is_read_from_its_own_env_var(monkeypatch):
    """An alias the save path writes is one the load path has to answer to.

    `MUSICGEN_API_KEY` reaches its field with nothing in config.yaml; the
    ACE-Step block already read `ACE_STEP_ENABLED`, `_MODE` and `_API_URL` and
    skipped only the key, so the one variable that is a secret was the one
    variable the loader ignored.
    """
    monkeypatch.setenv("ACE_STEP_API_KEY", FROM_ENV)
    config = Config()

    _apply_env_overrides(config)

    assert config.ace_step.api_key == FROM_ENV


def test_the_anthropic_key_reaches_the_reader_from_its_own_env_var(monkeypatch):
    """The name on the tin: a Claude key is not called OPENAI_API_KEY."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", FROM_ENV)
    config = Config()
    config.llm.provider = "anthropic"

    _apply_env_overrides(config)

    assert config.llm.api_key == FROM_ENV


def test_the_configured_provider_decides_which_key_wins(monkeypatch):
    """Two keys in one environment is normal; reading the wrong one is a 401."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "the-claude-key")
    monkeypatch.setenv("OPENAI_API_KEY", "the-openai-key")

    anthropic_side = Config()
    anthropic_side.llm.provider = "anthropic"
    openai_side = Config()
    openai_side.llm.provider = "openai"

    _apply_env_overrides(anthropic_side)
    _apply_env_overrides(openai_side)

    assert anthropic_side.llm.api_key == "the-claude-key"
    assert openai_side.llm.api_key == "the-openai-key"


_CREDENTIAL_ALIASES = [
    ("immich.api_key", "IMMICH_API_KEY"),
    ("llm.api_key", "OPENAI_API_KEY"),
    ("llm.api_key", "ANTHROPIC_API_KEY"),
    ("musicgen.api_key", "MUSICGEN_API_KEY"),
    ("ace_step.api_key", "ACE_STEP_API_KEY"),
    ("auth.password", "IMMICH_MEMORIES_AUTH_PASSWORD"),
]


@pytest.mark.parametrize(("path", "alias"), _CREDENTIAL_ALIASES)
def test_every_credential_alias_expands_as_a_reference_in_the_file(
    path: str, alias: str, tmp_path: Path, monkeypatch
):
    """`${ALIAS}` in config.yaml must resolve on its own.

    Asserted through `from_yaml` alone, because `_apply_env_overrides` would answer
    the same variable a second time and hide a field whose `${VAR}` expansion was
    never wired up -- which is exactly how the ACE-Step key stayed broken.
    """
    section, field = path.split(".")
    monkeypatch.setenv(alias, FROM_ENV)
    source = tmp_path / "config.yaml"
    source.write_text(f"{section}:\n  {field}: ${{{alias}}}\n")

    assert getattr(getattr(Config.from_yaml(source), section), field) == FROM_ENV


@pytest.mark.parametrize(
    ("provider", "other_alias", "header_name"),
    [
        ("anthropic", "OPENAI_API_KEY", "x-api-key"),
        ("zai", "OPENAI_API_KEY", "x-api-key"),
        ("openai", "ANTHROPIC_API_KEY", "Authorization"),
        ("openai-compatible", "ANTHROPIC_API_KEY", "Authorization"),
    ],
)
def test_an_unrelated_providers_key_never_reaches_the_request_header(
    monkeypatch, provider: str, other_alias: str, header_name: str
):
    """A key belonging to one host must not be posted to another host.

    Asserted on the header rather than on the field, because the header is what
    actually leaves the machine: an explicit key the operator configured was
    being replaced by whichever alias happened to be exported.
    """
    from immich_memories.analysis.llm_wire import anthropic_headers, openai_headers

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv(other_alias, "someone-elses-key")
    config = Config()
    config.llm.provider = provider
    config.llm.api_key = "the-key-the-operator-configured"

    _apply_env_overrides(config)

    headers = (
        anthropic_headers(config.llm) if header_name == "x-api-key" else openai_headers(config.llm)
    )
    assert "someone-elses-key" not in headers.get(header_name, "")
    assert "the-key-the-operator-configured" in headers[header_name]


@pytest.mark.parametrize(
    ("provider", "unrelated_alias"),
    [
        ("anthropic", "OPENAI_API_KEY"),
        ("zai", "OPENAI_API_KEY"),
        ("openai", "ANTHROPIC_API_KEY"),
        ("openai-compatible", "ANTHROPIC_API_KEY"),
    ],
)
@pytest.mark.parametrize("configured_key", ["", "explicit-provider-key"])
def test_the_full_load_does_not_borrow_another_providers_key(
    tmp_path: Path, monkeypatch, provider: str, unrelated_alias: str, configured_key: str
):
    """The whole load path, where `IMMICH_MEMORIES_LLM__API_KEY` is the explicit route."""
    from immich_memories import config_loader

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv(unrelated_alias, "someone-elses-key")
    monkeypatch.setenv("IMMICH_MEMORIES_LLM__PROVIDER", provider)
    monkeypatch.setenv("IMMICH_MEMORIES_LLM__API_KEY", configured_key)
    monkeypatch.setattr(config_loader, "_config", None)

    config = config_loader.get_config(reload=True)

    assert config.llm.api_key == configured_key


def test_a_hosted_key_the_config_file_states_survives_the_local_servers_alias(
    tmp_path: Path, monkeypatch
):
    """`OPENAI_API_KEY` is what every OpenAI-SDK client reads, local servers included.

    On a machine whose shell exports it for an mlx/vLLM server, the name says
    nothing about which endpoint the key belongs to, so it cannot outrank a key
    the config file names next to `provider: openai`. It did, and the hosted
    reader spent a whole run sending a local bearer token to api.openai.com,
    401 per call, ending as "no readable episode evidence".
    """
    from immich_memories.config import load_config, set_config

    monkeypatch.setenv("OPENAI_API_KEY", "the-local-servers-bearer-token")
    source = tmp_path / "config.yaml"
    source.write_text("llm:\n  provider: openai\n  model: gpt-5.6-luna\n  api_key: sk-hosted\n")

    try:
        config = load_config(source)
    finally:
        set_config(None)

    assert config.llm.api_key == "sk-hosted"


def test_the_alias_still_supplies_a_key_the_file_left_to_the_environment(
    tmp_path: Path, monkeypatch
):
    """A `${VAR}` nobody set is not a key, so the shorthand is still free to fill it."""
    from immich_memories.config import load_config, set_config

    monkeypatch.delenv("OPENAI_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", FROM_ENV)
    source = tmp_path / "config.yaml"
    source.write_text("llm:\n  provider: openai\n  api_key: ${OPENAI_KEY}\n")

    try:
        config = load_config(source)
    finally:
        set_config(None)

    assert config.llm.api_key == FROM_ENV
