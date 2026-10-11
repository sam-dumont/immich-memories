"""What the server runs or overwrites, and where the render worker is, is chosen in config.yaml or
the environment, never from the settings page: a signed-in web user must not pick a program to
execute, a file to overwrite, or the host that receives every Immich key."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from immich_memories.config_loader import get_config, load_config, set_config
from immich_memories.settings_edit import SettingRefused, save_settings

# key, a value the form could send
FILE_ONLY = [
    ("render.worker_base_url", "https://worker.example.test"),
    ("render.worker_token", "worker-token-0123456789abcdef"),
    ("editorial.preparation.detector_python", "/bin/sh"),
    ("editorial.preparation.detector_cache_dir", "/var/models/hf"),
    ("editorial.preparation.marqo_onnx", "/etc/target.onnx"),
    ("triage.encoder", "/etc/encoder.onnx"),
    ("free_text.wordnet", "/etc/wordnet.zip"),
    ("editorial.laya_checkpoint", "/etc/laya.zip"),
    ("llm.local_server", "/bin/sh"),
]


@pytest.fixture
def config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("IMMICH_MEMORIES_SECRET_KEY", "k" * 40)
    monkeypatch.setenv("IMMICH_MEMORIES_STORAGE_SECRET", "s" * 40)
    path = tmp_path / "config.yaml"
    path.write_text("")
    load_config(path)
    yield path
    set_config(None)


@pytest.mark.parametrize(("key", "value"), FILE_ONLY)
def test_the_settings_api_refuses_a_key_that_picks_what_the_server_runs(config_path, key, value):
    from immich_memories.web.server import create_app

    client = TestClient(create_app(), follow_redirects=False)

    response = client.post("/api/v1/settings", json={"values": {key: value}})

    assert response.status_code == 422
    assert key in response.json()["detail"]
    assert "config.yaml" in response.json()["detail"]
    assert value not in response.json()["detail"]


@pytest.mark.parametrize(("key", "value"), FILE_ONLY)
def test_a_refused_key_leaves_the_config_alone(config_path, key, value):
    with pytest.raises(SettingRefused, match="config.yaml"):
        save_settings({key: value})

    current: object = get_config(reload=True)
    for part in key.split("."):
        current = getattr(current, part)
    assert current != value


def test_the_store_itself_will_not_hold_such_a_key(config_path):
    from immich_memories.settings_store import settings_store

    store = settings_store(get_config(), create=True)
    assert store is not None
    with pytest.raises(ValueError, match="cannot be stored"):
        store.save({"editorial.preparation.detector_python": "/bin/sh"})
