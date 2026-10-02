"""The documented API-key permissions work against the disposable gate Immich."""

from __future__ import annotations

import uuid

import httpx
import pytest

from immich_memories.api.sync_client import SyncImmichClient
from immich_memories.config_loader import Config
from tests.e2e.fake_library import CAST, LIBRARY
from tests.integration.immich_fixtures import requires_immich
from tests.integration.immich_gate.conftest import FIXTURE_MONTH
from tests.integration.immich_gate.gate_cli import gate_store_url
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
    "timeline.read",
    "tag.read",
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
