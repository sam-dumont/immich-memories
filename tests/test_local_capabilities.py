"""Local capability reports distinguish configuration from actual execution."""

from immich_memories.config import Config
from immich_memories.local_capabilities import local_capabilities


def test_disabled_and_external_reader_are_not_certified():
    config = Config()
    rows = local_capabilities(config)
    assert next(row for row in rows if row.name == "Owned reader").status == "disabled"
    config.llm.enabled = True
    config.llm.base_url = "https://example.invalid/v1"
    rows = local_capabilities(config)
    reader = next(row for row in rows if row.name == "Owned reader")
    assert reader.status == "configured-external"
    assert "not certified by local verification" in reader.message


def test_local_reader_reports_files_as_unverified_not_inference(tmp_path):
    config = Config()
    config.llm.enabled = True
    config.llm.local_server = str(tmp_path / "llama-server")
    config.llm.model = str(tmp_path / "model.gguf")
    assert local_capabilities(config)[0].status == "missing"
    server = tmp_path / "llama-server"
    server.write_text("#!/bin/sh\nexit 99\n")
    server.chmod(0o700)
    (tmp_path / "model.gguf").write_bytes(b"not loaded by inspection")
    assert local_capabilities(config)[0].status == "unverified"
    assert "not been tested" in local_capabilities(config)[0].message


def test_music_configuration_and_installation_are_distinct(monkeypatch):
    config = Config()
    assert (
        next(row for row in local_capabilities(config) if row.name == "Local music").status
        == "disabled"
    )
    config.ace_step.enabled = True
    assert (
        next(row for row in local_capabilities(config) if row.name == "Local music").status
        == "configured-external"
    )
    config.ace_step.mode = "lib"
    # WHY: substitute model/process I/O so this contract test never starts native inference.
    monkeypatch.setattr(
        "immich_memories.audio.generators.ace_step_isolated.isolated_python", lambda: None
    )
    monkeypatch.setattr(
        "immich_memories.audio.generators.ace_step_runtime.is_ace_step_importable", lambda: False
    )
    assert (
        next(row for row in local_capabilities(config) if row.name == "Local music").status
        == "missing"
    )


def test_verification_never_calls_external_or_disabled_components():
    import asyncio

    from immich_memories.local_capabilities import verify_local_capabilities

    config = Config()
    config.llm.enabled = True
    config.llm.base_url = "https://example.invalid/v1"

    async def forbidden(_config):
        raise AssertionError("External/disabled setup must not enter native verification")

    rows = asyncio.run(verify_local_capabilities(config, verifier=forbidden))
    assert rows[0].status == "configured-external"
    assert not any(row.status == "verified" for row in rows)


def test_verification_cannot_certify_a_disabled_component(monkeypatch):
    import asyncio

    from immich_memories.local_capabilities import verify_local_capabilities
    from immich_memories.setup_capabilities import Capability

    config = Config()
    config.llm.enabled = True
    # WHY: substitute model/process I/O so this contract test never starts native inference.
    monkeypatch.setattr(
        "immich_memories.local_inference.local_reader_files", lambda _: ("server", [])
    )

    async def synthetic(_config):
        return [
            Capability("Owned reader", "verified", "synthetic text/JSON/vision only"),
            Capability("Local music", "verified", "should not overwrite disabled"),
        ]

    rows = asyncio.run(verify_local_capabilities(config, verifier=synthetic))
    assert rows[0].status == "verified"
    assert rows[1].status == "disabled"


def test_audio_validation_rejects_silent_or_truncated_generation(tmp_path):
    import numpy as np
    import pytest
    import soundfile as sf

    from immich_memories.local_capabilities import _check_audio

    path = tmp_path / "audio.wav"
    sf.write(path, np.zeros(1500), 100)
    with pytest.raises(RuntimeError, match="silent"):
        _check_audio(path, audible=True)
    sf.write(path, np.ones(100), 100)
    with pytest.raises(RuntimeError, match="15 seconds"):
        _check_audio(path, audible=True)
    sf.write(path, np.ones(1500) * 0.1, 100)
    _check_audio(path, audible=True)


async def test_reader_smoke_uses_text_json_vision_and_releases_owned_runtime(monkeypatch, tmp_path):
    from unittest.mock import AsyncMock

    from immich_memories.local_capabilities import verify_local_capabilities

    config = Config()
    config.llm.enabled = True
    config.llm.model = str(tmp_path / "reader.gguf")
    config.llm.local_mmproj = str(tmp_path / "vision.gguf")
    # WHY: substitute model/process I/O so this contract test never starts native inference.
    monkeypatch.setattr(
        "immich_memories.local_inference.local_reader_files", lambda _: ("server", [])
    )
    query = AsyncMock(side_effect=["yellow", '{"color":"yellow"}', "red"])
    release = AsyncMock()
    monkeypatch.setattr("immich_memories.analysis.llm_query.query_llm", query)
    monkeypatch.setattr("immich_memories.local_inference.local_models.release", release)
    rows = await verify_local_capabilities(config)
    assert rows[0].status == "verified"
    assert query.await_count == 3
    assert query.call_args_list[1].kwargs["response_format"]["json_schema"]["schema"]["properties"][
        "color"
    ]["enum"] == ["yellow"]
    assert query.call_args_list[2].kwargs["images"]
    assert release.await_count == 2


async def test_reader_refusal_still_releases_owned_runtime(monkeypatch):
    from unittest.mock import AsyncMock

    from immich_memories.local_capabilities import verify_local_capabilities

    config = Config()
    config.llm.enabled = True
    # WHY: substitute model/process I/O so this contract test never starts native inference.
    monkeypatch.setattr(
        "immich_memories.local_inference.local_reader_files", lambda _: ("server", [])
    )
    monkeypatch.setattr(
        "immich_memories.analysis.llm_query.query_llm",
        AsyncMock(side_effect=RuntimeError("local refusal")),
    )
    release = AsyncMock()
    monkeypatch.setattr("immich_memories.local_inference.local_models.release", release)
    rows = await verify_local_capabilities(config)
    assert rows[0].status == "blocked"
    assert "local refusal" in rows[0].message
    assert release.await_count == 2


async def test_local_verification_blocks_missing_assets_before_generation(monkeypatch, tmp_path):
    from unittest.mock import AsyncMock

    from immich_memories.local_capabilities import verify_local_capabilities

    config = Config()
    config.ace_step.enabled = True
    config.ace_step.mode = "lib"
    # WHY: substitute model/process I/O so this contract test never starts native inference.
    monkeypatch.setattr(
        "immich_memories.audio.generators.ace_step_isolated.isolated_python",
        lambda: tmp_path / "python",
    )
    monkeypatch.setattr(
        "immich_memories.audio.generators.memory_budget.memory_shortfall", lambda *_: None
    )

    def missing(_config):
        raise RuntimeError("Missing local checkpoints; no download attempted")

    monkeypatch.setattr("immich_memories.local_capabilities._check_audio_assets", missing)
    generation = AsyncMock(side_effect=AssertionError("Must not start generation"))
    monkeypatch.setattr(
        "immich_memories.audio.generators.ace_step_backend.ACEStepBackend.generate", generation
    )
    rows = await verify_local_capabilities(config)
    music = next(row for row in rows if row.name == "Local music")
    assert music.status == "blocked"
    assert "Missing local checkpoints" in music.message
    generation.assert_not_awaited()


async def test_owned_reader_is_released_before_rechecking_audio_budget(monkeypatch, tmp_path):
    from immich_memories.local_capabilities import verify_local_capabilities
    from immich_memories.setup_capabilities import Capability

    config = Config()
    config.ace_step.enabled = True
    config.ace_step.mode = "lib"
    warm = [True]
    # WHY: substitute model/process I/O so this contract test never starts native inference.
    monkeypatch.setattr(
        "immich_memories.audio.generators.ace_step_isolated.isolated_python",
        lambda: tmp_path / "python",
    )
    monkeypatch.setattr(
        "immich_memories.audio.generators.memory_budget.memory_shortfall",
        lambda *_: "Owned reader occupies budget" if warm[0] else None,
    )

    async def release():
        warm[0] = False

    async def audio(_config, _directory):
        assert not warm[0], "Warm reader must not cause a false audio refusal"
        return [Capability("Local music", "verified", "15-second synthetic audio")]

    monkeypatch.setattr("immich_memories.local_inference.local_models.release", release)
    monkeypatch.setattr("immich_memories.local_capabilities._verify_audio", audio)
    rows = await verify_local_capabilities(config)
    assert next(row for row in rows if row.name == "Local music").status == "verified"


async def test_reader_connection_failure_is_reported_and_owned_runtime_released(monkeypatch):
    from unittest.mock import AsyncMock

    import httpx

    from immich_memories.local_capabilities import verify_local_capabilities

    config = Config()
    config.llm.enabled = True
    # WHY: replace the native/network boundary with a real HTTPX refusal, not model inference.
    monkeypatch.setattr(
        "immich_memories.local_inference.local_reader_files", lambda _: ("server", [])
    )
    monkeypatch.setattr(
        "immich_memories.analysis.llm_query.query_llm",
        AsyncMock(side_effect=httpx.ConnectError("owned reader refused connection")),
    )
    release = AsyncMock()
    monkeypatch.setattr("immich_memories.local_inference.local_models.release", release)
    rows = await verify_local_capabilities(config)
    assert rows[0].status == "blocked"
    assert "refused connection" in rows[0].message
    assert release.await_count == 2


async def test_postrelease_music_refusal_replaces_stale_budget(monkeypatch, tmp_path):
    from immich_memories.local_capabilities import verify_local_capabilities

    config = Config()
    config.ace_step.enabled = True
    config.ace_step.mode = "lib"
    released = [False]
    # WHY: simulate a changing live memory reading across the real lifecycle boundary.
    monkeypatch.setattr(
        "immich_memories.audio.generators.ace_step_isolated.isolated_python",
        lambda: tmp_path / "python",
    )
    monkeypatch.setattr(
        "immich_memories.audio.generators.memory_budget.memory_shortfall",
        lambda *_: "Current cgroup refusal" if released[0] else "Stale warm reader estimate",
    )

    async def release():
        released[0] = True

    monkeypatch.setattr("immich_memories.local_inference.local_models.release", release)
    rows = await verify_local_capabilities(config)
    music = next(row for row in rows if row.name == "Local music")
    assert music.status == "blocked"
    assert music.message == "Current cgroup refusal"


async def test_weights_a_render_already_fetched_pass_the_asset_check(monkeypatch, tmp_path):
    # #2149: the check read the checkpoint root while renders load its pinned snapshot.
    from unittest.mock import AsyncMock

    from immich_memories.audio.generators.ace_step_checkpoints import pinned_checkpoints
    from immich_memories.local_capabilities import verify_local_capabilities
    from tests.ace_step_downloads import snapshot_module

    config = Config()
    config.ace_step.enabled = True
    config.ace_step.mode = "lib"
    config.ace_step.model_variant = "turbo"
    config.ace_step.use_lm = False
    monkeypatch.setenv("ACESTEP_CHECKPOINTS_DIR", str(tmp_path / "checkpoints"))
    # WHY: tiny weight files replace the remote multi-gigabyte snapshot a render fetches.
    monkeypatch.setattr("huggingface_hub.snapshot_download", snapshot_module().snapshot_download)
    with pinned_checkpoints(tmp_path / "checkpoints", "acestep-v15-turbo", None):
        pass
    # WHY: substitute model/process I/O so this contract test never starts native inference.
    monkeypatch.setattr(
        "immich_memories.audio.generators.ace_step_isolated.isolated_python",
        lambda: tmp_path / "python",
    )
    monkeypatch.setattr(
        "immich_memories.audio.generators.memory_budget.memory_shortfall", lambda *_: None
    )
    generation = AsyncMock(side_effect=RuntimeError("generation reached"))
    monkeypatch.setattr(
        "immich_memories.audio.generators.ace_step_backend.ACEStepBackend.generate", generation
    )

    rows = await verify_local_capabilities(config)

    music = next(row for row in rows if row.name == "Local music")
    assert music.message == "generation reached"
