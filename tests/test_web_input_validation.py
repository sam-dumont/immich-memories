"""Malformed requests get useful client errors through the real application."""

import json

import pytest
from fastapi.testclient import TestClient

from immich_memories.config_loader import set_config
from immich_memories.web.server import create_app
from tests.web_api_fixtures import config_in, save_run


@pytest.fixture
def client(tmp_path):
    config = config_in(tmp_path)
    set_config(config)
    save_run(config, "input-check")
    return TestClient(create_app())


def test_removing_a_relationship_for_a_missing_person_returns_a_client_error(client):
    response = client.request(
        "DELETE",
        "/api/v1/roster/missing/relationships",
        json={"kind": "spouse", "target_id": "missing-two"},
    )
    assert response.status_code == 404
    assert response.json()["detail"]


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/v1/cuts", {"ask": "\x00"}),
        ("/api/v1/runs/input-check/renders", {"title": "\x00", "music": "none"}),
    ],
)
def test_nul_in_command_fields_is_refused_before_a_job_is_created(client, path, body):
    response = client.post(path, json=body)
    assert response.status_code == 422
    assert client.get("/api/v1/jobs/active").json() is None


@pytest.mark.parametrize("field", ["ask", "year", "\ud800"])
@pytest.mark.parametrize("character", ["\ud800", "\udfff"])
def test_invalid_unicode_in_json_values_and_keys_returns_a_serializable_error(
    client, field, character
):
    response = client.post(
        "/api/v1/cuts/command",
        content=json.dumps({field: character}, ensure_ascii=True),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]


@pytest.mark.parametrize("body", ['{"ask":' + "[" * 1100 + "0" + "]" * 1100 + "}", '{"ask":'])
def test_invalid_or_excessively_nested_json_returns_a_client_error(client, body):
    response = client.post(
        "/api/v1/cuts/command", content=body, headers={"content-type": "application/json"}
    )
    assert response.status_code == 400
    assert response.json()["detail"]


@pytest.mark.parametrize("identifier", ["**x", "*", "upload-abc", "preview-abc"])
def test_music_lookup_rejects_patterns_and_partial_ids(client, tmp_path, identifier):
    folder = tmp_path / "cache" / "web-music"
    folder.mkdir(parents=True)
    (folder / ("upload-" + "abc" + "0" * 29 + ".mp3")).write_bytes(b"saved track")
    assert client.get(f"/api/v1/music/{identifier}").status_code == 404


@pytest.mark.parametrize(("filename", "payload"), [("bad.wav", b"RIFF"), ("bad.mp3", b"ID3")])
def test_a_truncated_soundtrack_is_rejected_without_leaving_a_track(
    client, tmp_path, filename, payload
):
    response = client.post("/api/v1/music", files={"file": (filename, payload)})
    assert response.status_code == 422
    assert not list((tmp_path / "cache" / "web-music").glob("*"))


@pytest.mark.parametrize(
    "content_type", ["application/json; charset=utf-8", "application/problem+json"]
)
def test_json_media_types_share_validation_and_preserve_valid_unicode(client, content_type):
    headers = {"content-type": content_type} if content_type else {}
    refused = client.post("/api/v1/cuts/command", content='{"ask":"\\ud800"}', headers=headers)
    assert refused.status_code == 422
    accepted = client.post(
        "/api/v1/cuts/command", content=json.dumps({"ask": "été 🚀"}), headers=headers
    )
    assert accepted.status_code == 200
    assert "été 🚀" in accepted.text


def test_nested_json_is_bounded_even_when_the_decoder_accepts_it(client):
    response = client.post(
        "/api/v1/cuts/command",
        content='{"ask":' + "[" * 70 + "0" + "]" * 70 + "}",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400
