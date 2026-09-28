"""Settings show each setting and its source, save edits to the database, and empty the caches."""

from __future__ import annotations

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
