"""Deployment wiring supplies defaults without locking the Settings page."""

import os

import pytest

from immich_memories.config_loader import Config


def test_gpu_compose_defaults_wire_services_below_saved_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("IMMICH_MEMORIES_DEPLOYMENT_TIER", "gpu")
    path = tmp_path / "config.yaml"
    path.write_text("tier: basic\n")

    defaults = Config.from_yaml(path, stored={})
    saved = Config.from_yaml(path, stored={"inference.facts_base_url": "https://model-box.example"})

    assert defaults.inference.facts_base_url == "http://immich-memories-inference:8092"
    assert (
        defaults.editorial.preparation.caption_base_url
        == "http://immich-memories-captioner:8092/v1"
    )
    assert saved.inference.facts_base_url == "https://model-box.example"
    assert defaults.tier == "basic"


def test_reader_url_and_model_require_explicit_activation(monkeypatch, tmp_path):
    monkeypatch.setenv("IMMICH_MEMORIES_DEPLOYMENT_TIER", "full")
    monkeypatch.setenv("IMMICH_MEMORIES_DEPLOYMENT_READER_URL", "http://reader.example:8000/v1")
    monkeypatch.setenv("IMMICH_MEMORIES_DEPLOYMENT_READER_MODEL", "reader-model")
    path = tmp_path / "config.yaml"
    path.write_text("tier: basic\n")

    disabled = Config.from_yaml(path, stored={})
    monkeypatch.setenv("IMMICH_MEMORIES_DEPLOYMENT_READER_ENABLED", "true")
    enabled = Config.from_yaml(path, stored={})
    saved_disabled = Config.from_yaml(path, stored={"llm.enabled": False})

    assert disabled.llm.base_url == "http://reader.example:8000/v1"
    assert disabled.llm.model == "reader-model"
    assert not disabled.llm.enabled
    assert enabled.llm.enabled
    assert not saved_disabled.llm.enabled


def test_full_preset_requires_activation_and_saved_tier_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("IMMICH_MEMORIES_DEPLOYMENT_TIER", "full")
    monkeypatch.setenv("IMMICH_MEMORIES_DEPLOYMENT_READER_MODEL", "reader-model")
    path = tmp_path / "missing.yaml"
    with pytest.raises(ValueError, match="full needs an enabled LLM"):
        Config.from_yaml(path, stored={})

    monkeypatch.setenv("IMMICH_MEMORIES_DEPLOYMENT_READER_ENABLED", "true")
    full = Config.from_yaml(path, stored={})
    saved = Config.from_yaml(path, stored={"tier": "basic"})

    assert full.tier == "full"
    assert saved.tier == "basic"


def test_gpu_box_uses_the_combined_worker_address(monkeypatch, tmp_path):
    monkeypatch.setenv("IMMICH_MEMORIES_DEPLOYMENT_TIER", "gpu")
    monkeypatch.setenv("IMMICH_MEMORIES_DEPLOYMENT_GPU_BOX", "192.168.1.50")
    path = tmp_path / "config.yaml"
    path.write_text("tier: basic\n")

    config = Config.from_yaml(path, stored={})

    assert config.inference.facts_base_url == "http://192.168.1.50:8092"
    assert config.editorial.preparation.caption_base_url == "http://192.168.1.50:8092/v1"
    assert config.inference.fallback_to_local
    assert not config.render.worker_base_url


def test_native_and_kubernetes_urls_are_editable_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("IMMICH_MEMORIES_DEPLOYMENT_TIER", "gpu")
    monkeypatch.setenv("IMMICH_MEMORIES_DEPLOYMENT_INFERENCE_URL", "")
    monkeypatch.setenv("IMMICH_MEMORIES_DEPLOYMENT_CAPTION_URL", "http://localhost:8092/v1")
    path = tmp_path / "config.yaml"
    path.write_text("tier: basic\n")

    native = Config.from_yaml(path, stored={})
    assert native.inference.facts_base_url == ""
    assert native.editorial.preparation.caption_base_url == "http://localhost:8092/v1"

    monkeypatch.setenv("IMMICH_MEMORIES_DEPLOYMENT_INFERENCE_URL", "http://inference:8092")
    monkeypatch.setenv("IMMICH_MEMORIES_DEPLOYMENT_CAPTION_URL", "http://captioner:8092/v1")
    kubernetes = Config.from_yaml(path, stored={})
    assert kubernetes.inference.facts_base_url == "http://inference:8092"
    assert kubernetes.editorial.preparation.caption_base_url == "http://captioner:8092/v1"


def test_runtime_env_beats_deployment_and_saved_url(monkeypatch, tmp_path):
    monkeypatch.setenv("IMMICH_MEMORIES_DEPLOYMENT_TIER", "gpu")
    monkeypatch.setenv("IMMICH_MEMORIES_INFERENCE__FACTS_BASE_URL", "https://operator.example")
    path = tmp_path / "config.yaml"
    path.write_text("tier: basic\n")
    config = Config.from_yaml(path, stored={"inference.facts_base_url": "https://saved.example"})
    assert config.inference.facts_base_url == "https://operator.example"


def test_without_deployment_env_existing_defaults_are_unchanged(monkeypatch, tmp_path):
    for key in tuple(os.environ):
        if key.startswith("IMMICH_MEMORIES_DEPLOYMENT_"):
            monkeypatch.delenv(key)
    assert (
        Config.from_yaml(tmp_path / "missing.yaml", stored={}).model_dump() == Config().model_dump()
    )


@pytest.mark.parametrize(
    "address,expected",
    [
        ("worker.example:9000", "http://worker.example:9000"),
        ("2001:db8::50", "http://[2001:db8::50]:8092"),
        ("[2001:db8::50]:9000", "http://[2001:db8::50]:9000"),
    ],
)
def test_gpu_box_accepts_ports_and_ipv6(monkeypatch, tmp_path, address, expected):
    monkeypatch.setenv("IMMICH_MEMORIES_DEPLOYMENT_TIER", "gpu")
    monkeypatch.setenv("IMMICH_MEMORIES_DEPLOYMENT_GPU_BOX", address)
    path = tmp_path / "config.yaml"
    path.write_text("tier: basic\n")
    config = Config.from_yaml(path, stored={})
    assert config.inference.facts_base_url == expected
    assert config.editorial.preparation.caption_base_url == expected + "/v1"


@pytest.mark.parametrize(
    "address", ["worker:", "worker:bad-port", "user:password@worker", "worker/path"]
)
def test_invalid_gpu_box_is_rejected_before_any_connection(monkeypatch, tmp_path, address):
    # WHY: the autouse path guard constructs Config during teardown, before monkeypatch undo.
    with monkeypatch.context() as invalid:
        invalid.setenv("IMMICH_MEMORIES_DEPLOYMENT_TIER", "gpu")
        invalid.setenv("IMMICH_MEMORIES_DEPLOYMENT_GPU_BOX", address)
        with pytest.raises(ValueError, match="GPU_BOX must be"):
            Config.from_yaml(tmp_path / "missing.yaml", stored={"tier": "basic"})


def test_invalid_deployment_tier_is_actionable(monkeypatch, tmp_path):
    with monkeypatch.context() as invalid:
        invalid.setenv("IMMICH_MEMORIES_DEPLOYMENT_TIER", "unknown")
        with pytest.raises(ValueError, match="must be basic, gpu or full"):
            Config.from_yaml(tmp_path / "missing.yaml", stored={})


def test_reader_secret_default_remains_editable_and_runtime_env_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("IMMICH_MEMORIES_DEPLOYMENT_READER_API_KEY", "deployment-test-value")
    path = tmp_path / "config.yaml"
    path.write_text("tier: basic\n")
    default = Config.from_yaml(path, stored={})
    saved = Config.from_yaml(path, stored={"llm.api_key": "saved-test-value"})
    assert default.llm.api_key == "deployment-test-value"
    assert saved.llm.api_key == "saved-test-value"
    assert not default.llm.enabled
    monkeypatch.setenv("IMMICH_MEMORIES_LLM__API_KEY", "runtime-test-value")
    runtime = Config.from_yaml(path, stored={"llm.api_key": "saved-test-value"})
    assert runtime.llm.api_key == "runtime-test-value"
