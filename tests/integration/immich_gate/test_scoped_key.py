"""The documented API-key permissions work against the disposable gate Immich."""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx
import pytest

from immich_memories.api.sync_client import SyncImmichClient
from immich_memories.config_loader import Config
from immich_memories.tracking import RunDatabase
from immich_memories.tracking.models import DeliveryStatus
from tests.e2e.fake_library import CAST, LIBRARY
from tests.integration.immich_fixtures import requires_immich
from tests.integration.immich_gate.conftest import FIXTURE_MONTH
from tests.integration.immich_gate.gate_cli import gate_store_url, run_cli
from tests.integration.immich_gate.seed import ADMIN_EMAIL, ADMIN_PASSWORD
from tests.integration.immich_gate.test_upload import _CAPTURED, _read_by_immich, _render

pytestmark = [requires_immich]

# Permission names come from Immich's v2.7.5/v3.2.2 server/src/enum.ts and
# each endpoint's @Authenticated decorator, not labels guessed from the UI.
READ_PERMISSIONS = [
    "user.read",
    "face.read",
    "asset.read",
    "asset.view",
    "asset.download",
    "asset.statistics",
    "person.read",
    "person.statistics",
    "album.read",
    "map.search",
]
DELIVERY_PERMISSIONS = [
    "asset.upload",
    "album.create",
    "albumAsset.create",
    "tag.create",
    "tag.asset",
]


@pytest.fixture
def scoped_key_client(gate_config, gate_version):
    """Create and revoke scoped keys only on the standard gate's seeded instance."""
    gate_store_url()
    home = Config.get_default_path().parent.parent
    assert home.name in {f"home-{gate_version}-sqlite", f"home-{gate_version}-postgresql"}
    clients = []
    keys = []
    with httpx.Client(base_url=f"{gate_config.immich.url}/api", timeout=30) as admin:
        login = admin.post("/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        login.raise_for_status()
        admin.headers["Authorization"] = f"Bearer {login.json()['accessToken']}"

        def create(permissions):
            answer = admin.post(
                "/api-keys", json={"name": "gate-scoped", "permissions": permissions}
            )
            answer.raise_for_status()
            key = answer.json()
            keys.append(key["apiKey"]["id"])
            client = SyncImmichClient(base_url=gate_config.immich.url, api_key=key["secret"])
            clients.append(client)
            return client

        try:
            yield create
        finally:
            for client in clients:
                client.close()
            for key in keys:
                admin.delete(f"/api-keys/{key}").raise_for_status()


def test_documented_minimum_reads_the_library(scoped_key_client, gate_client, tmp_path):
    client = scoped_key_client(READ_PERMISSIONS)
    assert client.validate_connection()
    assert client.get_current_user().email == ADMIN_EMAIL
    with httpx.Client(
        base_url=f"{client.base_url}/api", headers={"x-api-key": client.api_key}, timeout=30
    ) as http:
        assert set(http.get("/api-keys/me").json()["permissions"]) == set(READ_PERMISSIONS)
        location = http.get("/map/reverse-geocode", params={"lat": 51.5, "lon": -0.1})
        location.raise_for_status()
    photos = client.get_photos_for_date_range(FIXTURE_MONTH)
    assert len(photos) == sum(not p.is_video for p in LIBRARY)
    picture = next(p for p in LIBRARY if not p.is_video and p.people)
    asset = next(a for a in photos if a.original_file_name == picture.filename)
    assert client.get_asset(asset.id).exif_info is not None
    assert len(client.get_asset_faces(asset.id)) == len(picture.people)
    assert client.get_asset_thumbnail(asset.id)
    assert client.download_asset(asset.id, tmp_path / "original.jpg").stat().st_size > 0
    people = client.get_all_people()
    assert set(CAST) <= {p.name for p in people}
    assert client.get_person_asset_count(people[0].id) > 0
    assert client.count_assets_with_people([people[0].id]) > 0
    assert client.list_albums()
    assert client.get_time_buckets()
    assert client.generated_asset_ids() == gate_client.generated_asset_ids()


def test_documented_delivery_permissions_file_and_tag_a_film(
    scoped_key_client, gate_client, tmp_path
):
    client = scoped_key_client(READ_PERMISSIONS + DELIVERY_PERMISSIONS)
    album_name = f"Scoped gate {uuid.uuid4().hex[:8]}"
    answer = None
    try:
        answer = client.upload_memory(
            _render(tmp_path / "film", "green"), album_name, captured_at=_CAPTURED
        )
        assert _read_by_immich(client, answer["asset_id"])
        assert answer["asset_id"] in client.generated_asset_ids()
        reader = scoped_key_client(READ_PERMISSIONS)
        assert answer["asset_id"] in reader.generated_asset_ids()
        assert client.resolve_album(album_name).id == answer["album_id"]
        assert answer["asset_id"] in {
            row["id"] for row in client.list_album_assets(answer["album_id"])
        }
    finally:
        if answer is not None:
            with httpx.Client(
                base_url=f"{gate_client.base_url}/api",
                headers={"x-api-key": gate_client.api_key},
                timeout=30,
            ) as admin:
                admin.request(
                    "DELETE", "/assets", json={"ids": [answer["asset_id"]], "force": True}
                ).raise_for_status()
                admin.delete(f"/albums/{answer['album_id']}").raise_for_status()


def test_missing_read_permission_refuses_a_cut(scoped_key_client, tmp_path):
    client = scoped_key_client([p for p in READ_PERMISSIONS if p != "asset.download"])
    trace = tmp_path / "must-not-select.txt"
    result = run_cli(
        "generate",
        "--memory-type",
        "monthly_highlights",
        "--year",
        "2024",
        "--month",
        "6",
        "--no-music",
        "--no-render",
        "--trace-selection",
        str(trace),
        api_key=client.api_key,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output[-4000:]
    assert "asset.download" in output, output[-4000:]
    assert not trace.exists(), "The cut started before checking required read permissions"


def test_read_only_key_keeps_a_finished_film_when_upload_is_requested(
    scoped_key_client, gate_store, gate_config, tmp_path, monkeypatch
):
    client = scoped_key_client(READ_PERMISSIONS)
    result = run_cli(
        "generate",
        "--memory-type",
        "monthly_highlights",
        "--year",
        "2024",
        "--month",
        "6",
        "--include-photos",
        "--no-music",
        "--duration",
        "20",
        "--quiet",
        "--output",
        str(tmp_path / "read-only.mp4"),
        "--upload-to-immich",
        api_key=client.api_key,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output[-4000:]
    runs = [
        run
        for run in RunDatabase(gate_store).list_runs(status="completed")
        if Path(run.output_path or "/").is_relative_to(tmp_path)
    ]
    assert len(runs) == 1, output[-4000:]
    run = runs[0]
    assert Path(run.output_path).stat().st_size > 0
    assert run.delivery_status is DeliveryStatus.ABANDONED
    assert "asset.upload" in run.delivery_error
    assert "asset.upload" in output
    assert run.output_path in output

    from immich_memories.db.bootstrap import URL_ENV
    from tests.web_server_fixtures import basic_auth_config, server_client, signed_session

    # WHY: the web server's configuration is external; use this gate's synthetic key/store.
    monkeypatch.setenv(URL_ENV, gate_store_url())
    config = gate_config.model_copy(deep=True)
    config.immich.api_key = client.api_key
    config.auth = basic_auth_config().auth
    web = server_client(monkeypatch, config)
    download = f"/api/v1/runs/{run.run_id}/download"
    assert web.get(download).status_code == 401
    web.cookies.set("session", signed_session(config))
    response = web.get(download)
    assert response.status_code == 200
    assert response.content == Path(run.output_path).read_bytes()
    assert response.headers["content-disposition"].startswith("attachment;")
