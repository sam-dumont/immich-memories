"""Application entry points establish mounted scratch before starting work."""

import tempfile
from pathlib import Path

from click.testing import CliRunner
from fastapi.testclient import TestClient


def test_cli_media_probe_uses_the_configured_cache(tmp_path, monkeypatch):
    from immich_memories.cli import main
    from immich_memories.processing import hardware

    mounted = tmp_path / "mounted-cache"
    monkeypatch.setenv("IMMICH_MEMORIES_CACHE__DIRECTORY", str(mounted))
    config = tmp_path / "config.yaml"
    config.write_text("{}\n")
    previous = tempfile.gettempdir()

    def probe():
        # WHY: hardware detection is an external boundary; its scratch files are real.
        with tempfile.TemporaryDirectory() as directory:
            assert Path(directory).is_relative_to(mounted)
        return hardware.HWAccelCapabilities()

    monkeypatch.setattr(hardware, "detect_hardware_acceleration", probe)
    for _ in range(2):
        result = CliRunner().invoke(main, ["--config", str(config), "hardware"])
        assert result.exit_code == 0, result.exception
        assert tempfile.gettempdir() == previous


def test_direct_web_startup_uses_mounted_scratch(tmp_path, monkeypatch):
    from immich_memories.config_loader import load_config, set_config
    from immich_memories.web.server import create_app

    mounted = tmp_path / "mounted-cache"
    monkeypatch.setenv("IMMICH_MEMORIES_CACHE__DIRECTORY", str(mounted))
    monkeypatch.setenv("IMMICH_MEMORIES_STORAGE_SECRET", "synthetic-session-key-" * 3)
    config = tmp_path / "config.yaml"
    config.write_text("{}\n")
    previous = tempfile.gettempdir()
    try:
        load_config(config)
        for _ in range(2):
            with TestClient(create_app()) as client:
                assert client.get("/health/live").status_code == 200
                with tempfile.TemporaryDirectory() as directory:
                    assert Path(directory).is_relative_to(mounted)
            assert tempfile.gettempdir() == previous
    finally:
        set_config(None)


def test_inference_service_uses_its_own_cache_for_scratch(tmp_path):
    from immich_memories_inference.app import create_app
    from immich_memories_inference.runtime import ProducerRuntime
    from immich_memories_inference.settings import InferenceSettings

    mounted = tmp_path / "inference-cache"
    previous = tempfile.gettempdir()
    for _ in range(2):
        # WHY: no model weights are needed to exercise the service's real startup/shutdown.
        with TestClient(
            create_app(InferenceSettings(cache_dir=mounted), runtime=ProducerRuntime({}))
        ) as client:
            assert client.get("/ping").json() == "pong"
            with tempfile.TemporaryDirectory() as directory:
                assert Path(directory).is_relative_to(mounted)
        assert tempfile.gettempdir() == previous


def test_render_worker_reopens_its_private_scratch_after_restart(tmp_path, monkeypatch):
    from unittest.mock import create_autospec

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "services/render-worker"))
    from immich_memories_render_worker.app import create_app
    from immich_memories_render_worker.renderer import Renderer
    from immich_memories_render_worker.settings import WorkerSettings

    mounted = tmp_path / "render-worker"
    token = "t" * 32
    settings = WorkerSettings(directory=mounted, token=token, immich_url="https://immich.invalid")
    previous = tempfile.gettempdir()
    for _ in range(2):
        # WHY: GPU/render hardware is outside the worker's real startup and scratch lifecycle.
        renderer = create_autospec(Renderer, instance=True)
        renderer.health.return_value = {"ready": True}
        with TestClient(create_app(settings, renderer=renderer)) as client:
            response = client.get("/health", headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == 200
            assert response.json()["ready"] is True
            assert Path(tempfile.gettempdir()) == mounted / "scratch"
            with tempfile.TemporaryDirectory() as directory:
                assert Path(directory).is_relative_to(mounted)
        assert tempfile.gettempdir() == previous
