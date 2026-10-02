"""Generated malformed input reaches the real app, with isolated paths and no provider work."""

import json
import sys

import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from immich_memories.config_loader import set_config
from immich_memories.web.job_routes import cli_executable
from immich_memories.web.server import create_app
from tests.web_api_fixtures import config_in, save_run

JSON_VALUE = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=80),
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=15), children, max_size=4)
    ),
    max_leaves=15,
)


@pytest.fixture
def real_client(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    config = config_in(tmp_path)
    config.output.directory = str(tmp_path / "films")
    set_config(config, path=tmp_path / "config.yaml")
    save_run(config, "generated-check")
    client = TestClient(create_app())
    executable = tmp_path / "no-provider-work"
    executable.write_text(f"#!{sys.executable}\nraise SystemExit(0)\n")
    executable.chmod(0o755)
    # WHY: CLI subprocesses would contact Immich; only the execution boundary is replaced.
    client.app.dependency_overrides[cli_executable] = lambda: str(executable)
    return client


def json_routes(client):
    for path, methods in client.app.openapi()["paths"].items():
        if not path.startswith("/api/v1/"):
            continue
        for method, operation in methods.items():
            if "application/json" not in operation.get("requestBody", {}).get("content", {}):
                continue
            for key, value in {
                "run_id": "generated-check",
                "person_id": "missing",
                "asset_id": "missing",
            }.items():
                path = path.replace("{" + key + "}", value)
            yield method, path


@settings(
    max_examples=35,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    st.one_of(st.text(max_size=80), st.integers(), st.booleans(), st.lists(JSON_VALUE, max_size=4))
)
def test_every_json_route_refuses_non_object_bodies(real_client, value):
    for method, path in json_routes(real_client):
        response = real_client.request(
            method, path, content=json.dumps(value), headers={"content-type": "application/json"}
        )
        assert 400 <= response.status_code < 500, (method, path, value, response.text)


@settings(
    max_examples=80,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(JSON_VALUE)
def test_edit_and_command_fields_never_escape_as_server_errors(real_client, value):
    for path, payload in [
        ("/api/v1/cuts/command", {"year": value, "ask": value, "duration": value}),
        (
            "/api/v1/runs/generated-check/revisions",
            {"removed": value, "segments": value, "swaps": value},
        ),
        ("/api/v1/roster", {"name": value}),
        ("/api/v1/pictures/missing/decision", {"action": value}),
    ]:
        response = real_client.post(
            path, content=json.dumps(payload), headers={"content-type": "application/json"}
        )
        assert response.status_code < 500, (path, payload, response.text)


@settings(
    max_examples=25,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(st.lists(st.integers() | st.text(max_size=200), min_size=1, max_size=5))
def test_every_json_route_validates_its_declared_fields(real_client, value):
    schema = real_client.app.openapi()
    for method, path in json_routes(real_client):
        template = next(
            template
            for template, operations in schema["paths"].items()
            if method in operations
            and template.replace("{run_id}", "generated-check")
            .replace("{person_id}", "missing")
            .replace("{asset_id}", "missing")
            == path
        )
        body = schema["paths"][template][method]["requestBody"]["content"]["application/json"][
            "schema"
        ]
        model = schema["components"]["schemas"][body["$ref"].rsplit("/", 1)[1]]
        payload = dict.fromkeys(model["properties"], value)
        response = real_client.request(method, path, json=payload)
        assert 400 <= response.status_code < 500, (method, path, payload, response.text)


@pytest.mark.parametrize(
    "identifier",
    ["..%2f..%2foutside", "%252e%252e%252foutside", "%2foutside", "x" * 5000, "%00", "%EF%BF%BD"],
)
def test_path_parameters_do_not_escape_their_store(real_client, tmp_path, identifier):
    sentinel = tmp_path / "outside"
    sentinel.write_text("keep me")
    for path in [
        "/runs/{id}",
        "/runs/{id}/cut",
        "/runs/{id}/film",
        "/jobs/{id}",
        "/jobs/{id}/output",
        "/ask/preview/{id}",
        "/music/{id}",
    ]:
        response = real_client.get("/api/v1" + path.replace("{id}", identifier))
        assert 400 <= response.status_code < 500, (path, response.text)
    for path, payload in [
        ("/roster/{id}/relationships", {"kind": "spouse", "target_id": "missing"}),
        ("/pictures/{id}/decision", {"action": "clear"}),
        ("/caches/{id}/clear", None),
    ]:
        response = real_client.post("/api/v1" + path.replace("{id}", identifier), json=payload)
        assert response.status_code < 500, (path, response.text)
    assert sentinel.read_text() == "keep me"
