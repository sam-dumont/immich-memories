"""Settings show the configuration that runs, secrets masked, and empty the caches on request."""

from __future__ import annotations

from unittest.mock import patch

from tests.web_api_fixtures import api_client, config_in


def test_the_active_config_is_shown_with_every_secret_masked(tmp_path):
    config = config_in(tmp_path)
    config.immich.api_key = "a-very-secret-key"
    # WHY: get_config reads the real file; the test hands it this config.
    with patch("immich_memories.web.settings.get_config", return_value=config):
        body = api_client(config).get("/api/v1/config").json()

    assert body["sections"]["immich"]["api_key"] == "***"
    assert "a-very-secret-key" not in str(body)


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
