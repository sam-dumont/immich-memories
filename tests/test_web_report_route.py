"""The web client's report preview is #1428's report route, mounted with the rest of /api/v1."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# The builder lands with #1464; until this branch carries it, there is no route to hit.
pytest.importorskip("immich_memories.tracking.report_api")


@pytest.fixture
def client() -> TestClient:
    from immich_memories.config_loader import Config, get_config
    from immich_memories.web import mount_web

    app = FastAPI()
    mount_web(app)
    # WHY: supply isolated configuration instead of the developer's configuration file.
    app.dependency_overrides[get_config] = lambda: Config()
    return TestClient(app)


def test_the_page_previews_the_redacted_report_the_cli_builds(client):
    from immich_memories.tracking import RunTracker

    tracker = RunTracker(capture_system=False)
    tracker.start_run(person_name="Marigold")
    tracker.fail_run("Marigold is missing")

    response = client.get(f"/api/v1/runs/{tracker.run_id}/report")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"markdown", "has_flagged_photos"}
    assert body["has_flagged_photos"] is False
    assert "Marigold" not in body["markdown"]


def test_a_run_that_is_not_there_has_no_report(client):
    assert client.get("/api/v1/runs/20000101_000000_none/report").status_code == 404


def test_the_report_is_typed_and_asks_for_a_session(client):
    from immich_memories.web.auth import is_bypass_path

    schema = client.app.openapi()
    response = schema["paths"]["/api/v1/runs/{run_id}/report"]["get"]["responses"]["200"]

    assert response["content"]["application/json"]["schema"]["$ref"].endswith("/ReportResponse")
    assert not is_bypass_path("/api/v1/runs/20000101_000000_none/report")


def test_the_page_downloads_the_same_redacted_bundle_the_cli_writes(client):
    import io
    import zipfile

    from immich_memories.tracking import RunTracker

    tracker = RunTracker(capture_system=False)
    tracker.start_run(person_name="Marigold")
    tracker.fail_run("Marigold is missing")

    response = client.get(f"/api/v1/runs/{tracker.run_id}/report/bundle")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "attachment" in response.headers["content-disposition"]
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert sorted(archive.namelist()) == ["report.json", "report.md", "run.log"]
    assert all(b"Marigold" not in archive.read(name) for name in archive.namelist())


def test_a_run_that_is_not_there_has_no_bundle(client):
    assert client.get("/api/v1/runs/20000101_000000_none/report/bundle").status_code == 404
