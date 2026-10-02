"""Normal app settings must reach the local runtime's bounded CUDA mode."""

import pytest

from immich_memories.audio.generators.ace_step_backend import ACEStepBackend
from immich_memories.audio.generators.factory import _app_config_to_ace_step
from immich_memories.config_models_soundtrack import ACEStepConfig


def test_config_default_reaches_backend_runtime_and_keeps_api_key(monkeypatch):
    settings = ACEStepConfig(mode="lib", api_key="test-only-key")
    assert settings.cpu_offload is True
    backend = ACEStepBackend(_app_config_to_ace_step(settings))
    captured = []
    # WHY: record the real config→factory→backend crossing without allocating native weights.
    monkeypatch.setattr(
        "immich_memories.audio.generators.ace_step_backend.build_v15_runtime",
        lambda **kwargs: captured.append(kwargs),
    )
    backend._init_pipeline()
    assert captured[0]["cpu_offload"] is True
    assert backend.config.extra_args["api_key"] == "test-only-key"


def test_explicit_false_reaches_backend(monkeypatch):
    backend = ACEStepBackend(_app_config_to_ace_step(ACEStepConfig(mode="lib", cpu_offload=False)))
    captured = []
    # WHY: keep the runtime allocation boundary observable without allocating model tensors.
    monkeypatch.setattr(
        "immich_memories.audio.generators.ace_step_backend.build_v15_runtime",
        lambda **kwargs: captured.append(kwargs),
    )
    backend._init_pipeline()
    assert captured[0]["cpu_offload"] is False


@pytest.mark.parametrize(
    "device,enabled,expected",
    [("cuda", True, True), ("cuda", False, False), ("mps", True, False), ("cpu", True, True)],
)
def test_real_runtime_resolves_offload_for_device(monkeypatch, tmp_path, device, enabled, expected):
    import sys
    from types import ModuleType

    from immich_memories.audio.generators import ace_step_runtime as runtime
    from tests.ace_step_downloads import snapshot_module

    modules = {"huggingface_hub": snapshot_module()}
    for name in [
        "acestep",
        "acestep.handler",
        "acestep.inference",
        "acestep.llm_inference",
        "acestep.model_downloader",
    ]:
        modules[name] = ModuleType(name)
    modules["acestep"].__file__ = str(tmp_path / "acestep/__init__.py")
    modules["acestep.handler"].AceStepHandler = object
    modules["acestep.inference"].GenerationConfig = object
    modules["acestep.inference"].GenerationParams = object
    modules["acestep.inference"].generate_music = lambda: None
    modules["acestep.llm_inference"].LLMHandler = object
    modules["acestep.model_downloader"].ensure_lm_model = lambda: None
    # WHY: execute app runtime policy while substituting upstream/native model allocation boundaries.
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setenv("ACESTEP_CHECKPOINTS_DIR", str(tmp_path / "checkpoints"))
    monkeypatch.setattr(runtime, "_local_runtime_target", lambda: (device, "pt", False))
    monkeypatch.setattr(runtime, "memory_shortfall", lambda *_: None)
    captured = []
    monkeypatch.setattr(
        runtime, "_initialize_dit_handler", lambda *_, **kwargs: captured.append(kwargs)
    )
    monkeypatch.setattr(runtime, "_initialize_lm_handler", lambda *_, **_kwargs: None)
    runtime.build_v15_runtime(
        model_variant="turbo",
        lm_model_size="1.7B",
        use_lm=False,
        disable_offload=False,
        cpu_offload=enabled,
    )
    assert captured[0]["offload"] is expected


async def test_api_payload_and_auth_are_unchanged_by_local_offload(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from immich_memories.audio.generators.base import GenerationRequest

    captured = {}

    class Client:
        def __init__(self, **kwargs):
            captured["headers"] = kwargs["headers"]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, url, json):
            captured["body"] = json
            return SimpleNamespace(
                raise_for_status=lambda: None, json=lambda: {"task_id": "synthetic"}
            )

    backend = ACEStepBackend(
        _app_config_to_ace_step(
            ACEStepConfig(mode="api", api_key="test-only-key", cpu_offload=True)
        )
    )
    # WHY: observe the real HTTP request construction without contacting a provider or downloading audio.
    monkeypatch.setattr("httpx.AsyncClient", Client)
    monkeypatch.setattr(backend, "_poll_and_download", AsyncMock())
    await backend._generate_api(
        GenerationRequest(prompt="warm", duration_seconds=15, output_dir=tmp_path)
    )
    assert captured["headers"] == {"Authorization": "Bearer test-only-key"}
    assert "cpu_offload" not in captured["body"]
    assert captured["body"]["duration"] == 15


def test_cpu_offload_environment_override_is_read_by_regular_config(monkeypatch):
    from immich_memories.config import Config

    # WHY: isolate the documented environment setting from this developer's saved configuration.
    monkeypatch.setenv("IMMICH_MEMORIES_ACE_STEP__CPU_OFFLOAD", "false")
    config = Config()
    assert config.ace_step.cpu_offload is False
    assert _app_config_to_ace_step(config.ace_step).extra_args["cpu_offload"] is False
