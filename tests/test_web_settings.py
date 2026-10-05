"""Settings show each setting and its source, save edits to the database, and empty the caches."""

from __future__ import annotations

import pytest

from immich_memories.config_loader import set_config
from tests.web_api_fixtures import api_client, config_in


def _settings_client(tmp_path, monkeypatch, config_text: str = ""):
    from immich_memories.config_loader import load_config
    from immich_memories.web.dependencies import config_file

    path = tmp_path / "config.yaml"
    path.write_text(config_text)
    load_config(path)
    client = api_client(config_in(tmp_path))
    client.app.dependency_overrides[config_file] = lambda: path
    return client, path


def _rows(body: dict) -> dict:
    return {row["key"]: row for section in body["sections"] for row in section["settings"]}


def test_every_setting_shows_where_it_comes_from_and_secrets_stay_masked(tmp_path, monkeypatch):
    monkeypatch.setenv("IMMICH_MEMORIES_OUTPUT__RESOLUTION", "720p")
    client, _ = _settings_client(
        tmp_path,
        monkeypatch,
        "immich:\n  api_key: a-very-secret-key\nadvanced:\n  llm:\n    model: file-model\n",
    )

    body = client.get("/api/v1/settings").json()
    rows = _rows(body)

    assert rows["immich.api_key"]["value"] == "***"
    assert "a-very-secret-key" not in str(body)
    assert (rows["llm.model"]["source"], rows["llm.model"]["editable"]) == ("file", False)
    assert rows["output.resolution"]["override"] == "IMMICH_MEMORIES_OUTPUT__RESOLUTION"
    assert rows["defaults.transition_duration"]["source"] == "default"


def test_a_saved_setting_goes_to_the_database_and_never_to_config_yaml(tmp_path, monkeypatch):
    client, path = _settings_client(tmp_path, monkeypatch)
    before = path.read_bytes()

    saved = client.post("/api/v1/settings", json={"values": {"output.resolution": "4k"}})
    refused = client.post("/api/v1/settings", json={"values": {"auth.allowed_emails": "[not json"}})

    assert saved.status_code == 200
    assert _rows(saved.json())["output.resolution"]["source"] == "database"
    assert path.read_bytes() == before
    assert refused.status_code == 422 and "not valid JSON" in refused.json()["detail"]
    set_config(None)


def test_a_cache_reports_its_size_and_clears_on_request(tmp_path):
    config = config_in(tmp_path)
    thumbs = config.cache.cache_path / "thumbnails"
    thumbs.mkdir(parents=True)
    client = api_client(config)
    from immich_memories.cache import ThumbnailCache

    ThumbnailCache(cache_dir=thumbs, max_size_mb=10).put("asset-1", "thumbnail", b"jpeg-bytes")

    before = {c["name"]: c for c in client.get("/api/v1/caches").json()}
    cleared = client.post("/api/v1/caches/thumbnail/clear").json()
    after = {c["name"]: c for c in client.get("/api/v1/caches").json()}

    assert before["thumbnail"]["items"] == 1 and cleared["removed"] == 1
    assert after["thumbnail"]["items"] == 0


def test_only_the_caches_a_run_still_fills_are_listed_and_cleared(tmp_path):
    """The Analysis table and the old players' preview folder hold nothing a run reads (#1508)."""
    client = api_client(config_in(tmp_path))

    listed = [c["name"] for c in client.get("/api/v1/caches").json()]

    assert listed == ["video", "thumbnail"]
    for retired in ("analysis", "preview"):
        assert client.post(f"/api/v1/caches/{retired}/clear").status_code == 422


def test_global_fade_default_can_be_saved_and_invalid_colours_are_refused(tmp_path, monkeypatch):
    client, _ = _settings_client(tmp_path, monkeypatch)
    assert (
        _rows(client.get("/api/v1/settings").json())["title_screens.fade_color"]["value"] == "white"
    )

    saved = client.post("/api/v1/settings", json={"values": {"title_screens.fade_color": "black"}})
    assert saved.status_code == 200
    assert _rows(saved.json())["title_screens.fade_color"]["value"] == "black"
    refused = client.post("/api/v1/settings", json={"values": {"title_screens.fade_color": "blue"}})
    assert refused.status_code == 422
    assert (
        _rows(client.get("/api/v1/settings").json())["title_screens.fade_color"]["value"] == "black"
    )
    set_config(None)


def test_deployment_service_defaults_remain_editable_and_saved_settings_win(tmp_path, monkeypatch):
    monkeypatch.setenv("IMMICH_MEMORIES_DEPLOYMENT_TIER", "basic")
    defaults = {
        "IMMICH_MEMORIES_DEPLOYMENT_INFERENCE_URL": "http://inference:8092",
        "IMMICH_MEMORIES_DEPLOYMENT_CAPTION_URL": "http://captioner:8092/v1",
        "IMMICH_MEMORIES_DEPLOYMENT_READER_URL": "http://reader.example.lan:8000/v1",
        "IMMICH_MEMORIES_DEPLOYMENT_READER_MODEL": "default-served-model",
        "IMMICH_MEMORIES_DEPLOYMENT_READER_ENABLED": "true",
    }
    for name, value in defaults.items():
        monkeypatch.setenv(name, value)
    client, path = _settings_client(tmp_path, monkeypatch)
    before = path.read_bytes()
    rows = _rows(client.get("/api/v1/settings").json())
    assert rows["inference.facts_base_url"]["value"] == "http://inference:8092"
    assert rows["llm.model"]["value"] == "default-served-model"
    changes = {
        "inference.facts_base_url": "http://192.168.1.50:8092",
        "editorial.preparation.caption_base_url": "http://192.168.1.50:8092/v1",
        "llm.base_url": "https://reader.example.net/v1",
        "llm.model": "another-served-model",
        "llm.enabled": False,
    }
    assert all(rows[key]["editable"] and rows[key]["source"] == "default" for key in changes)

    saved = client.post("/api/v1/settings", json={"values": changes})

    assert saved.status_code == 200
    reloaded = _rows(client.get("/api/v1/settings").json())
    assert all(reloaded[key]["source"] == "database" for key in changes)
    assert {key: reloaded[key]["value"] for key in changes} == changes
    assert path.read_bytes() == before
    set_config(None)


def test_legacy_tier_in_saved_settings_is_refused(tmp_path, monkeypatch):
    from immich_memories.config_loader import Config
    from immich_memories.db import open_store
    from immich_memories.settings_store import SettingsStore

    _, path = _settings_client(tmp_path, monkeypatch)
    config = Config.from_yaml(path, stored={})
    store = open_store(config)
    try:
        SettingsStore(store, None).save({"tier": "nas"})
    finally:
        store.engine.dispose()
    with pytest.raises(ValueError, match="tier 'nas' is now called 'basic': set tier: basic"):
        Config.from_yaml(path)
    set_config(None)
