"""Finished films are downloadable only through an authenticated saved run."""

import pytest

from immich_memories.tracking.models import DeliveryStatus
from tests.web_api_fixtures import api_client, config_in, save_run
from tests.web_server_fixtures import basic_auth_config, server_client, signed_session

RUN = "20261002_120000_aaaa"


def _film(tmp_path, **fields):
    config = config_in(tmp_path)
    path = tmp_path / "finished.mp4"
    path.write_bytes(b"synthetic finished film")
    save_run(config, RUN, cut=False, status="completed", output_path=str(path), **fields)
    return config, path


def test_retained_film_download_is_an_attachment_for_the_recorded_run(tmp_path):
    config, path = _film(
        tmp_path,
        delivery_status=DeliveryStatus.PENDING,
        delivery_error="not uploaded: the key lacks asset.upload",
    )
    response = api_client(config).get(f"/api/v1/runs/{RUN}/download")
    assert response.status_code == 200
    assert response.content == path.read_bytes()
    assert response.headers["content-disposition"].startswith("attachment;")
    assert "finished.mp4" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "private, no-store"


def test_download_requires_a_valid_signed_session(tmp_path, monkeypatch):
    config, path = _film(tmp_path)
    config.auth = basic_auth_config().auth
    client = server_client(monkeypatch, config)
    assert client.get(f"/api/v1/runs/{RUN}/download").status_code == 401
    client.cookies.set("session", signed_session(config))
    assert client.get(f"/api/v1/runs/{RUN}/download").content == path.read_bytes()


@pytest.mark.parametrize("unsafe", ["symlink", "nonfilm", "unknown"])
def test_download_refuses_other_files_and_unknown_runs(tmp_path, unsafe):
    config, path = _film(tmp_path)
    if unsafe == "symlink":
        path.unlink()
        private = tmp_path / "private.txt"
        private.write_bytes(b"private")
        path.symlink_to(private)
    elif unsafe == "nonfilm":
        from immich_memories.db import open_store
        from immich_memories.tracking import RunDatabase

        database = RunDatabase(open_store(config))
        record = database.get_run(RUN)
        record.output_path = str(tmp_path / "private.txt")
        database.update_run_status(RUN, "completed", output_path=record.output_path)
        (tmp_path / "private.txt").write_bytes(b"private")
    response = api_client(config).get(
        f"/api/v1/runs/{'missing' if unsafe == 'unknown' else RUN}/download"
    )
    assert response.status_code == 404
    assert b"private" not in response.content


def test_reclaimed_delivered_film_downloads_only_its_recorded_asset_and_cleans_cache(tmp_path):
    from immich_memories.web.film_downloads import immich_finished_film

    config, path = _film(
        tmp_path, delivery_status=DeliveryStatus.DELIVERED, immich_asset_id="recorded-film-42"
    )
    path.unlink()
    fetched = []

    def fetch(asset_id, target, size):
        fetched.append((asset_id, target))
        target.write_bytes(b"delivered original film")
        return target

    client = api_client(config)
    client.app.dependency_overrides[immich_finished_film] = lambda: fetch
    response = client.get(f"/api/v1/runs/{RUN}/download?asset_id=someone-else&path=/private/key")
    assert response.status_code == 200
    assert response.content == b"delivered original film"
    assert fetched[0][0] == "recorded-film-42"
    assert not fetched[0][1].exists()
    assert response.headers["content-disposition"].startswith("attachment;")


def test_remote_download_failure_removes_partial_file_and_has_no_secret_error(tmp_path):
    from immich_memories.web.film_downloads import immich_finished_film

    config, path = _film(
        tmp_path, delivery_status=DeliveryStatus.DELIVERED, immich_asset_id="recorded-film-42"
    )
    path.unlink()
    partials = []

    def fetch(asset_id, target, size):
        partials.append(target)
        target.write_bytes(b"partial")
        raise ValueError("secret-provider-key")

    client = api_client(config)
    client.app.dependency_overrides[immich_finished_film] = lambda: fetch
    response = client.get(f"/api/v1/runs/{RUN}/download")
    assert response.status_code == 502
    assert "secret-provider-key" not in response.text
    assert not partials[0].exists()


@pytest.mark.parametrize("asset_id", ["../private", "https://other.example/original", ""])
def test_reclaimed_film_cannot_address_a_browser_or_invalid_asset(tmp_path, asset_id):
    config, path = _film(
        tmp_path, delivery_status=DeliveryStatus.DELIVERED, immich_asset_id=asset_id
    )
    path.unlink()
    assert api_client(config).get(f"/api/v1/runs/{RUN}/download").status_code == 404
