"""Which requests the server answers at all: the Host they name, and where a write comes from."""

from __future__ import annotations

import asyncio
import io
import os
import wave
from pathlib import Path

import pytest

from immich_memories.config_loader import Config
from tests.web_server_fixtures import basic_auth_config, server_client


def _open_config(tmp_path: Path, **server: object) -> Config:
    return Config(
        immich={"url": "http://immich.lan:2283", "api_key": "stored-immich-key"},
        cache={"database": str(tmp_path / "runs.db"), "directory": str(tmp_path / "cache")},
        server=server or {},
    )


def test_without_auth_a_host_that_is_not_local_or_allowed_is_misdirected(monkeypatch, tmp_path):
    client = server_client(monkeypatch, _open_config(tmp_path))

    response = client.get("/api/v1/connection", headers={"Host": "rebind.attacker.example"})

    assert response.status_code == 421
    assert "server.allowed_hosts" in response.text
    assert "stored-immich-key" not in response.text


@pytest.mark.parametrize("host", ["localhost:8080", "127.0.0.1:8080", "[::1]:8080", "localhost"])
def test_without_auth_the_local_names_are_answered(monkeypatch, tmp_path, host):
    client = server_client(monkeypatch, _open_config(tmp_path))

    assert client.get("/api/v1/connection", headers={"Host": host}).status_code == 200


def test_health_probes_are_answered_whatever_host_they_name(monkeypatch, tmp_path):
    client = server_client(monkeypatch, _open_config(tmp_path))

    for path in ("/health/live", "/health/ready"):
        response = client.get(path, headers={"Host": "10.0.0.5:8080"})
        assert response.status_code != 421, path
    assert client.get("/health", headers={"Host": "10.0.0.5:8080"}).status_code == 421


@pytest.mark.parametrize(
    ("server", "public_url", "host"),
    [
        ({"allowed_hosts": ["nas.lan"]}, "", "nas.lan:8080"),
        ({"allowed_hosts": ["NAS.lan:8080"]}, "", "nas.lan"),
        ({"host": "192.168.1.20"}, "", "192.168.1.20:8080"),
        ({}, "https://memories.example.org", "memories.example.org"),
    ],
)
def test_without_auth_the_configured_names_are_answered(
    monkeypatch, tmp_path, server, public_url, host
):
    config = _open_config(tmp_path, **server)
    config.auth.public_url = public_url
    client = server_client(monkeypatch, config)

    assert client.get("/api/v1/connection", headers={"Host": host}).status_code == 200


def _signed_in(monkeypatch, tmp_path, **server: object):
    config = basic_auth_config(**server)
    config.cache.directory = str(tmp_path / "cache")
    client = server_client(monkeypatch, config)
    login = client.post(
        "/auth/login",
        json={"username": "operator", "password": "test-password"},
        headers={"Host": "localhost"},
    )
    assert login.status_code == 200
    return client


def test_with_auth_any_host_is_answered_until_an_allow_list_is_set(monkeypatch, tmp_path):
    client = _signed_in(monkeypatch, tmp_path)

    response = client.get("/api/v1/connection", headers={"Host": "192.168.1.20:8080"})

    assert response.status_code == 200


def test_with_auth_and_an_allow_list_only_listed_and_local_hosts_are_answered(
    monkeypatch, tmp_path
):
    client = _signed_in(monkeypatch, tmp_path, allowed_hosts=["memories.lan"])

    assert client.get("/api/v1/connection", headers={"Host": "memories.lan"}).status_code == 200
    assert client.get("/api/v1/connection", headers={"Host": "localhost"}).status_code == 200
    assert client.get("/api/v1/connection", headers={"Host": "other.lan"}).status_code == 421


def test_with_auth_and_an_allow_list_the_public_url_is_still_answered(monkeypatch, tmp_path):
    config = basic_auth_config(allowed_hosts=["memories.lan"])
    config.auth.public_url = "https://memories.example.org"
    client = server_client(monkeypatch, config)

    response = client.get("/login", headers={"Host": "memories.example.org"})

    assert response.status_code != 421


def _local_client(monkeypatch, config: Config):
    client = server_client(monkeypatch, config)
    client.base_url = "http://localhost:8080"
    return client


def _uploads(config: Config) -> list[Path]:
    folder = config.cache.cache_path / "web-music"
    return sorted(folder.iterdir()) if folder.is_dir() else []


def test_a_write_another_site_started_is_refused_and_does_nothing(monkeypatch, tmp_path):
    config = _open_config(tmp_path)
    client = _local_client(monkeypatch, config)

    response = client.post(
        "/api/v1/music",
        files={"file": ("a.mp3", b"ID3" + b"\0" * 1024, "audio/mpeg")},
        headers={"Origin": "https://evil.example"},
    )

    assert response.status_code == 403
    assert _uploads(config) == []


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_a_write_the_browser_marks_as_from_another_site_is_refused(monkeypatch, tmp_path, site):
    client = _local_client(monkeypatch, _open_config(tmp_path))

    response = client.post("/api/v1/caches/thumbnail/clear", headers={"Sec-Fetch-Site": site})

    assert response.status_code == 403


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Sec-Fetch-Site": "same-origin", "Origin": "http://localhost:8080"},
        {"Sec-Fetch-Site": "none"},
        {"Origin": "http://localhost:8080"},
    ],
)
def test_a_write_from_this_origin_or_a_machine_client_goes_through(monkeypatch, tmp_path, headers):
    client = _local_client(monkeypatch, _open_config(tmp_path))

    response = client.post("/api/v1/caches/thumbnail/clear", headers=headers)

    assert response.status_code == 200


def test_settings_posted_from_another_origin_never_reach_the_route(monkeypatch, tmp_path):
    client = _local_client(monkeypatch, _open_config(tmp_path))
    evil = {"Origin": "https://evil.example"}

    as_text = client.post(
        "/api/v1/settings",
        content='{"values": {"immich.url": "http://elsewhere.example"}}',
        headers={"Content-Type": "text/plain", **evil},
    )
    as_form = client.post("/api/v1/settings", data={"values": "x"}, headers=evil)

    assert (as_text.status_code, as_form.status_code) == (403, 403)


def test_the_trigger_is_checked_for_origin_too_but_a_bare_machine_call_passes(
    monkeypatch, tmp_path
):
    client = _local_client(monkeypatch, _open_config(tmp_path, trigger_token="t" * 40))
    wrong_token = {"Authorization": "Bearer not-the-token"}

    from_a_page = client.post(
        "/api/trigger", headers={"Origin": "https://evil.example", **wrong_token}
    )
    from_a_cron_job = client.post("/api/trigger", headers=wrong_token)

    assert from_a_page.status_code == 403
    assert from_a_cron_job.status_code == 401


def _asgi_post(app, path: str, headers: dict[str, str], chunks: list[bytes]) -> dict:
    """POST straight through the ASGI app, recording what it answered and what it read."""
    sent: list[dict] = []
    read = {"chunks": 0}
    pending = list(chunks)

    async def receive():
        read["chunks"] += 1
        body = pending.pop(0) if pending else b""
        return {"type": "http.request", "body": body, "more_body": bool(pending)}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": ("127.0.0.1", 50000),
        "server": ("localhost", 8080),
    }
    asyncio.run(app(scope, receive, send))
    start = next(message for message in sent if message["type"] == "http.response.start")
    return {"status": start["status"], "chunks_read": read["chunks"]}


def _music_app(monkeypatch, config: Config):
    from immich_memories.web import server

    server_client(monkeypatch, config)
    return server.create_app()


def test_an_upload_announcing_more_than_the_limit_is_refused_before_its_body_is_read(
    monkeypatch, tmp_path
):
    config = _open_config(tmp_path)
    app = _music_app(monkeypatch, config)
    headers = {
        "host": "localhost:8080",
        "content-type": "multipart/form-data; boundary=x",
        "content-length": str(65 * 1024 * 1024),
    }

    answered = _asgi_post(app, "/api/v1/music", headers, [b"--x\r\n"])

    assert answered == {"status": 413, "chunks_read": 0}
    assert _uploads(config) == []


def test_an_upload_streamed_past_the_limit_is_cut_off(monkeypatch, tmp_path):
    config = _open_config(tmp_path)
    app = _music_app(monkeypatch, config)
    head = (
        b'--x\r\nContent-Disposition: form-data; name="file"; filename="a.mp3"\r\n'
        b"Content-Type: audio/mpeg\r\n\r\nID3"
    )
    megabyte = b"\0" * (1024 * 1024)
    headers = {"host": "localhost:8080", "content-type": "multipart/form-data; boundary=x"}

    answered = _asgi_post(app, "/api/v1/music", headers, [head, *[megabyte] * 70, b"\r\n--x--\r\n"])

    assert answered["status"] == 413
    assert answered["chunks_read"] < 70
    assert _uploads(config) == []


def test_uploads_past_the_quota_push_out_the_oldest(monkeypatch, tmp_path):
    config = _open_config(tmp_path, music_upload_quota_mb=1)
    client = _local_client(monkeypatch, config)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\0" * (400 * 1024))
    track = buffer.getvalue()

    ids = []
    for minute in range(3):
        uploaded = client.post("/api/v1/music", files={"file": ("a.wav", track, "audio/wav")})
        assert uploaded.status_code == 201
        ids.append(uploaded.json()["id"])
        # Upload times one minute apart, so "oldest" does not hang on the clock's resolution.
        for path in _uploads(config):
            if path.stem == ids[-1]:
                os.utime(path, (1_700_000_000 + 60 * minute,) * 2)

    kept = {path.stem for path in _uploads(config)}
    assert kept == {ids[1], ids[2]}


def test_every_response_says_it_may_not_be_framed(monkeypatch, tmp_path):
    client = _local_client(monkeypatch, _open_config(tmp_path))

    for response in (
        client.get("/api/v1/connection"),
        client.get("/api/v1/connection", headers={"Host": "rebind.example"}),
        client.post("/api/v1/caches/video/clear", headers={"Origin": "https://evil.example"}),
    ):
        assert response.headers["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
