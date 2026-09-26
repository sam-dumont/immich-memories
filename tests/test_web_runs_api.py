"""The web client reads runs through the same records the terminal reads."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from immich_memories.config_loader import Config
from immich_memories.tracking import RunDatabase
from immich_memories.tracking.models import RunMetadata
from immich_memories.web import mount_web
from immich_memories.web.dependencies import Playback, immich_playback, immich_preview
from tests.web_api_fixtures import api_client, config_in, save_run


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return config_in(tmp_path)


@pytest.fixture
def client(config: Config) -> TestClient:
    return api_client(config)


def _run(config: Config, run_id: str, when: datetime, *, cut: bool) -> None:
    save_run(config, run_id, when=when, cut=cut, memory_type="monthly")


def test_runs_come_newest_first_with_the_pictures_their_cut_plays(client, config):
    _run(config, "20260901_080000_aaaa", datetime(2026, 9, 1, 8, tzinfo=UTC), cut=False)
    _run(config, "20260913_080000_bbbb", datetime(2026, 9, 13, 8, tzinfo=UTC), cut=True)

    page = client.get("/api/v1/runs").json()

    assert [run["run_id"] for run in page["runs"]] == [
        "20260913_080000_bbbb",
        "20260901_080000_aaaa",
    ]
    assert page["runs"][0]["preview_asset_ids"] == ["garden-1", "lake-1"]
    assert page["runs"][1]["preview_asset_ids"] == []
    assert page["runs"][0]["created_at"] == "2026-09-13T08:00:00Z"


def _jpeg(px: int) -> bytes:
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (px, px), "teal").save(buffer, "JPEG")
    return buffer.getvalue()


def test_a_thumbnail_the_cache_lacks_is_fetched_from_immich_once(client, config):
    fetched: list[str] = []

    def fetch(asset_id: str) -> bytes:
        fetched.append(asset_id)
        return _jpeg(1440)

    # WHY: Immich is the external boundary; the unit tier has no Immich to read from.
    client.app.dependency_overrides[immich_preview] = lambda: fetch
    asset = "0b7a58b4-7f5e-4c3b-9d1e-1f2a3b4c5d6e"

    first = client.get(f"/api/v1/assets/{asset}/thumbnail")
    second = client.get(f"/api/v1/assets/{asset}/thumbnail")

    assert first.status_code == second.status_code == 200
    assert first.headers["content-type"] == "image/jpeg"
    assert fetched == [asset]


def test_the_client_reads_its_language_from_the_shared_interface_catalogue(client):
    answer = client.get("/api/v1/i18n", headers={"Accept-Language": "fr-BE,fr;q=0.9"}).json()

    assert answer["locale"] == "fr"
    assert answer["messages"]["Back to runs"] == "Retour aux exécutions"


def test_a_deep_link_into_the_client_loads_the_app_and_assets_load_as_files(tmp_path):
    built = tmp_path / "client"
    (built / "_app").mkdir(parents=True)
    (built / "index.html").write_text("<div id=app></div>")
    (built / "_app" / "start.js").write_text("export {}")
    app = FastAPI()
    mount_web(app, client_dir=built)
    browser = TestClient(app)

    assert browser.get("/app/runs/20260913_080000_bbbb").text == "<div id=app></div>"
    assert browser.get("/app/_app/start.js").text == "export {}"
    assert browser.get("/app/_app/missing.js").status_code == 404
    (tmp_path / "secret.txt").write_text("private")
    assert browser.get("/app/_app/..%2F..%2Fsecret.txt").status_code == 404


def test_the_client_api_answers_401_while_the_client_page_goes_to_login():
    from immich_memories.ui.app import _unauthenticated_response

    assert _unauthenticated_response("/api/v1/runs").status_code == 401
    assert _unauthenticated_response("/app/runs").status_code == 307


def test_runs_filter_by_status_and_page_forward(client, config):
    for day in range(1, 4):
        _run(config, f"2026090{day}_080000_aaaa", datetime(2026, 9, day, tzinfo=UTC), cut=False)
    RunDatabase(config.cache.database_path).save_run(
        RunMetadata(
            run_id="20260904_080000_ffff",
            created_at=datetime(2026, 9, 4, tzinfo=UTC),
            status="failed",
        )
    )

    failed = client.get("/api/v1/runs", params={"status": "failed"}).json()
    first = client.get("/api/v1/runs", params={"status": "completed", "limit": 2}).json()
    rest = client.get(
        "/api/v1/runs", params={"status": "completed", "offset": first["next_offset"]}
    ).json()

    assert [run["run_id"] for run in failed["runs"]] == ["20260904_080000_ffff"]
    assert len(first["runs"]) == 2 and first["next_offset"] == 2
    assert [run["run_id"] for run in rest["runs"]] == ["20260901_080000_aaaa"]
    assert rest["next_offset"] is None


def test_a_video_streams_the_range_the_browser_asked_immich_for(client):
    asked: list[tuple[str, str | None]] = []

    def playback(asset_id: str, byte_range: str | None) -> Playback:
        asked.append((asset_id, byte_range))
        return Playback(
            status=206,
            headers={"content-range": "bytes 100-199/5000", "content-length": "100"},
            chunks=iter([b"x" * 100]),
        )

    # WHY: Immich is the external boundary; the unit tier has no Immich to stream from.
    client.app.dependency_overrides[immich_playback] = lambda: playback
    asset = "0b7a58b4-7f5e-4c3b-9d1e-1f2a3b4c5d6e"

    response = client.get(f"/api/v1/assets/{asset}/video", headers={"Range": "bytes=100-199"})

    assert asked == [(asset, "bytes=100-199")]
    assert response.status_code == 206
    assert response.headers["content-range"] == "bytes 100-199/5000"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.content == b"x" * 100
