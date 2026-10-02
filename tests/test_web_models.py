"""A first install inspects its pinned downloads without starting one implicitly."""

from tests.web_api_fixtures import api_client, config_in


def test_first_start_lists_nas_downloads_without_creating_files_or_jobs(tmp_path):
    config = config_in(tmp_path)
    config.tier = "nas"
    config.triage.encoder = str(tmp_path / "models/encoder.onnx")
    config.free_text.wordnet = str(tmp_path / "models/wordnet.zip")
    client = api_client(config)

    response = client.get("/api/v1/models")

    assert response.status_code == 200
    manifest = response.json()
    assert manifest["ready"] is False
    encoder, wordnet = manifest["artifacts"]
    assert encoder["host"] == "github.com" and encoder["size"] == "88 MB"
    assert wordnet["host"] == "raw.githubusercontent.com" and wordnet["size"] == "11 MB"
    assert all(len(item["sha256"]) == 64 and not item["ready"] for item in manifest["artifacts"])
    assert not (tmp_path / "models").exists()
    assert client.get("/api/v1/jobs/active").json() is None


def test_authorized_download_is_the_existing_cli_job_with_followable_failure(tmp_path):
    import json
    import sys
    import time

    from immich_memories.web.job_routes import cli_executable

    client = api_client(config_in(tmp_path))
    recorded = tmp_path / "argv.json"
    executable = tmp_path / "immich-memories"
    executable.write_text(
        f"#!{sys.executable}\nimport json,sys\n"
        f'open({str(recorded)!r}, "w").write(json.dumps(sys.argv[1:]))\n'
        'print("models: 2/2 wordnet"); print("encoder: downloaded; wordnet: digest does not match")\nsys.exit(1)\n'
    )
    executable.chmod(0o755)
    client.app.dependency_overrides[cli_executable] = lambda: str(executable)

    response = client.post(
        "/api/v1/models/fetch", json={"plan_id": client.get("/api/v1/models").json()["plan_id"]}
    )

    assert response.status_code == 202
    job = response.json()
    assert job["kind"] == "models" and job["command"] == "immich-memories models fetch"
    for _ in range(100):
        job = client.get(f"/api/v1/jobs/{job['id']}").json()
        if job["status"] != "running":
            break
        time.sleep(0.05)
    assert job["status"] == "failed" and job["exit_code"] == 1
    assert job["progress"]["label"] == "wordnet"
    assert job["progress"]["done"] == 1 and job["progress"]["total"] == 2
    assert json.loads(recorded.read_text())[-2:] == ["models", "fetch"]
    assert (
        "digest does not match" in client.get(f"/api/v1/jobs/{job['id']}/output").json()["output"]
    )


def test_detector_tier_includes_revision_pinned_snapshot_even_without_hub_extra(tmp_path):
    config = config_in(tmp_path)
    config.editorial.detectors_enabled = True
    config.editorial.laya_audience = True
    client = api_client(config)

    manifest = client.get("/api/v1/models").json()

    snapshots = [item for item in manifest["artifacts"] if item["revision"]]
    assert snapshots and all(item["host"] == "huggingface.co" for item in snapshots)
    assert all(item["sha256"] is None for item in snapshots)


def test_model_acquisition_requires_the_real_server_session(monkeypatch, tmp_path):
    from tests.web_server_fixtures import basic_auth_config, server_client

    config = basic_auth_config()
    config.cache.directory = str(tmp_path / "cache")
    client = server_client(monkeypatch, config)

    assert client.post("/api/v1/models/fetch", json={}).status_code == 401
    assert not (config.cache.cache_path / "web-jobs").exists()


def test_signed_in_model_download_still_refuses_a_foreign_origin(monkeypatch, tmp_path):
    from tests.web_server_fixtures import basic_auth_config, server_client, signed_session

    config = basic_auth_config()
    config.cache.directory = str(tmp_path / "cache")
    client = server_client(monkeypatch, config)
    client.cookies.set("session", signed_session(config))

    response = client.post(
        "/api/v1/models/fetch", json={}, headers={"Origin": "https://evil.example"}
    )

    assert response.status_code == 403
    assert not (config.cache.cache_path / "web-jobs").exists()


def test_status_never_contacts_download_hosts_or_returns_url_credentials(monkeypatch, tmp_path):
    import socket
    import urllib.request

    config = config_in(tmp_path)
    config.tier = "nas"
    config.triage.encoder = str(tmp_path / "encoder.onnx")
    config.free_text.wordnet = str(tmp_path / "wordnet.zip")
    config.triage.encoder_url = "https://secret:password@example.com/weights?token=hidden"

    def refuse(*args, **kwargs):
        raise AssertionError("status must not authorize outbound traffic")

    # WHY: these are the external network boundaries, not acquisition-plan internals.
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    response = api_client(config).get("/api/v1/models")

    assert response.status_code == 200
    assert response.json()["artifacts"][0]["host"] == "example.com"
    assert all(secret not in response.text for secret in ("secret", "password", "hidden"))


def test_a_changed_download_host_requires_fresh_consent_before_any_job(tmp_path):
    config = config_in(tmp_path)
    config.tier = "nas"
    config.triage.encoder = str(tmp_path / "encoder.onnx")
    config.free_text.wordnet = str(tmp_path / "wordnet.zip")
    client = api_client(config)
    consent = client.get("/api/v1/models").json()["plan_id"]
    config.triage.encoder_url = "https://different.example/encoder.onnx"

    response = client.post("/api/v1/models/fetch", json={"plan_id": consent})

    assert response.status_code == 409
    assert "Review" in response.json()["detail"]
    assert client.get("/api/v1/jobs/active").json() is None


def test_non_ascii_consent_is_rejected_as_invalid_input_not_a_server_error(tmp_path):
    response = api_client(config_in(tmp_path)).post(
        "/api/v1/models/fetch", json={"plan_id": "invalid🦄"}
    )

    assert response.status_code == 422
