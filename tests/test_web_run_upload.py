"""A finished run's film goes to Immich from the run page, without rendering again."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

import pytest

from immich_memories.db import open_store
from immich_memories.tracking import RunDatabase
from immich_memories.web.render_capabilities import immich_render_capabilities
from immich_memories.web.run_upload import immich_opener
from tests.web_api_fixtures import api_client, config_in, save_run

RUN = "20261007_120000_aaaa"


class FakeImmich:
    """Records the one write the route makes: the upload."""

    def __init__(self, result: dict | None = None):
        self.uploads: list[tuple[Path, str | None]] = []
        self.result = result or {
            "asset_id": "asset-42",
            "album_id": "album-1",
            "delivery_complete": True,
            "missing_permissions": [],
            "warnings": [],
        }

    def upload_memory(self, video_path, album_name=None, *, captured_at=None):
        self.uploads.append((video_path, album_name))
        return self.result


def _setup(tmp_path, *, missing=(), film=True, immich=None):
    config = config_in(tmp_path)
    path = tmp_path / "finished.mp4"
    if film:
        path.write_bytes(b"synthetic finished film")
    save_run(config, RUN, cut=False, status="completed", output_path=str(path))
    client = api_client(config)
    fake = immich or FakeImmich()
    # WHY: Immich is the external boundary; the upload is the WRITE, the key scope is its check.
    client.app.dependency_overrides[immich_opener] = lambda: lambda: nullcontext(fake)
    client.app.dependency_overrides[immich_render_capabilities] = lambda: lambda: tuple(missing)
    return config, client, fake, path


def test_a_finished_film_is_uploaded_to_the_named_album_and_recorded_on_the_run(tmp_path):
    config, client, fake, path = _setup(tmp_path)

    response = client.post(f"/api/v1/runs/{RUN}/upload", json={"album": "Summer"})

    assert response.status_code == 200
    assert response.json()["asset_id"] == "asset-42"
    assert fake.uploads == [(path, "Summer")]
    saved = RunDatabase(open_store(config)).get_run(RUN)
    assert (saved.delivery_status.value, saved.immich_asset_id) == ("delivered", "asset-42")
    assert saved.delivery_album == "Summer"
    assert client.get(f"/api/v1/runs/{RUN}").json()["immich_asset_id"] == "asset-42"


def test_a_key_without_upload_scope_is_refused_with_the_reason_and_nothing_is_sent(tmp_path):
    _, client, fake, _ = _setup(tmp_path, missing=["asset.upload"])

    response = client.post(f"/api/v1/runs/{RUN}/upload", json={})

    assert response.status_code == 409
    assert "asset.upload" in response.json()["detail"]
    assert fake.uploads == []


def test_a_film_that_is_gone_says_so(tmp_path):
    _, client, fake, _ = _setup(tmp_path, film=False)

    response = client.post(f"/api/v1/runs/{RUN}/upload", json={})

    assert response.status_code == 409
    assert "film file" in response.json()["detail"]
    assert fake.uploads == []


def test_an_unknown_run_is_not_found(tmp_path):
    _, client, _, _ = _setup(tmp_path)

    assert client.post("/api/v1/runs/nope/upload", json={}).status_code == 404


def test_an_incomplete_delivery_is_reported_and_not_recorded_as_delivered(tmp_path):
    config, client, _, _ = _setup(
        tmp_path,
        immich=FakeImmich(
            {
                "asset_id": "asset-7",
                "album_id": None,
                "delivery_complete": False,
                "missing_permissions": ["album.create"],
                "warnings": ["delivery incomplete: the key lacks album.create"],
            }
        ),
    )

    response = client.post(f"/api/v1/runs/{RUN}/upload", json={})

    assert response.status_code == 502
    assert "album.create" in response.json()["detail"]
    saved = RunDatabase(open_store(config)).get_run(RUN)
    assert saved.delivery_status.value == "not_requested"


@pytest.mark.parametrize("body", [{}, {"album": None}])
def test_the_album_is_optional(tmp_path, body):
    _, client, fake, path = _setup(tmp_path)

    assert client.post(f"/api/v1/runs/{RUN}/upload", json=body).status_code == 200
    assert fake.uploads[0][0] == path
