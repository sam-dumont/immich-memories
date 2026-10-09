"""Standalone and combined render workers keep scratch in mounted storage."""

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import WORKER_TOKEN, worker_app


@pytest.mark.parametrize("combined", [False, True])
def test_worker_probe_and_requests_use_mounted_scratch(tmp_path, combined):
    mounted = tmp_path / "output"
    previous = tempfile.gettempdir()

    class Renderer:
        def health(self):
            # WHY: hardware probing is the boundary; scratch creation is real.
            with tempfile.TemporaryDirectory() as directory:
                assert Path(directory).is_relative_to(mounted)
            return {"ready": True}

    if combined:
        from immich_memories_render_worker.settings import WorkerSettings

        from immich_memories_inference.gpu_worker import create_app
        from immich_memories_inference.runtime import ProducerRuntime
        from immich_memories_inference.settings import InferenceSettings

        app = create_app(
            InferenceSettings(cache_dir=tmp_path / "cache"),
            WorkerSettings(
                token=WORKER_TOKEN, immich_url="http://immich.invalid", directory=mounted
            ),
            runtime=ProducerRuntime({}),
            renderer=Renderer(),
        )
    else:
        app = worker_app(mounted, Renderer())
    with TestClient(app), tempfile.TemporaryDirectory() as directory:
        assert Path(directory).is_relative_to(mounted)
    assert tempfile.gettempdir() == previous
