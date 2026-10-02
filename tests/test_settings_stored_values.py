"""Settings saved from the UI or the CLI are taken literally, and never follow a credential elsewhere."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from immich_memories.config_loader import get_config, load_config, set_config

ENV_SECRET = "env-secret-value-that-must-never-be-shown"
SIGNING_SECRET = "s" * 40


@pytest.fixture
def config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("IMMICH_MEMORIES_SECRET_KEY", "k" * 40)
    monkeypatch.setenv("IMMICH_MEMORIES_STORAGE_SECRET", SIGNING_SECRET)
    monkeypatch.setenv("SOME_DEPLOYMENT_SECRET", ENV_SECRET)
    path = tmp_path / "config.yaml"
    path.write_text("")
    load_config(path)
    yield path
    set_config(None)


@pytest.fixture
def client(config_path: Path) -> TestClient:
    from immich_memories.web.server import create_app

    return TestClient(create_app(), follow_redirects=False)


def test_a_setting_that_references_an_environment_variable_is_refused(client):
    response = client.post(
        "/api/v1/settings", json={"values": {"llm.model": "m-${SOME_DEPLOYMENT_SECRET}"}}
    )

    assert response.status_code == 422
    assert "environment variables" in response.json()["detail"]
    assert get_config(reload=True).llm.model != "m-${SOME_DEPLOYMENT_SECRET}"


def test_the_connection_refuses_a_url_that_references_an_environment_variable(client):
    response = client.put(
        "/api/v1/connection",
        json={"url": "http://x/${SOME_DEPLOYMENT_SECRET}", "api_key": "typed-key-0123456789"},
    )

    assert response.status_code == 422
    assert ENV_SECRET not in response.text


def _plant(key: str, value: object) -> None:
    """A row written before saves were checked: straight into the table, past every rule."""
    import sqlalchemy as sa

    from immich_memories.db import now_db, open_store, resolve_location
    from immich_memories.db.tables import settings

    store = open_store(location=resolve_location(get_config()))
    with store.begin() as conn:
        conn.execute(
            sa.insert(settings).values(
                key=key, value=value, secret=False, ciphertext=None, updated_at=now_db()
            )
        )


def test_a_stored_value_that_references_an_environment_variable_is_ignored(client):
    _plant("llm.model", "m-${SOME_DEPLOYMENT_SECRET}")

    config = get_config(reload=True)
    body = client.get("/api/v1/settings").text

    assert config.llm.model != f"m-{ENV_SECRET}"
    assert "${SOME_DEPLOYMENT_SECRET}" not in config.llm.model
    assert ENV_SECRET not in body


def test_preflight_names_a_stored_setting_it_ignores(config_path):
    from immich_memories.preflight import CheckStatus
    from immich_memories.preflight_settings import check_stored_settings

    _plant("llm.model", "m-${SOME_DEPLOYMENT_SECRET}")

    result = check_stored_settings(get_config(reload=True))

    assert result.status == CheckStatus.ERROR
    assert "llm.model" in (result.details or "")
    assert ENV_SECRET not in str(result)


AUTH_ON = "auth:\n  enabled: true\n  provider: basic\n  username: op\n  password: pw-123456789\n"


def _signed_in(config_path: Path) -> TestClient:
    from immich_memories.web.server import create_app

    config_path.write_text(AUTH_ON)
    load_config(config_path)
    client = TestClient(create_app(), follow_redirects=False)
    login = client.post("/auth/login", json={"username": "op", "password": "pw-123456789"})
    assert login.status_code == 200
    return client


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("auth.enabled", "false"),
        ("server.trigger_token", "t" * 40),
        ("auth.allowed_emails", '["someone@example.test"]'),
    ],
)
def test_who_can_reach_the_app_is_never_saved_from_settings(config_path, key, value):
    client = _signed_in(config_path)

    response = client.post("/api/v1/settings", json={"values": {key: value}})

    assert response.status_code == 422
    assert "environment or config.yaml" in response.json()["detail"]
    anonymous = TestClient(client.app, follow_redirects=False)
    assert anonymous.get("/api/v1/connection").status_code == 401


def test_no_settings_response_carries_an_environment_value(config_path, monkeypatch):
    monkeypatch.setenv("IMMICH_API_KEY", "immich-key-from-the-environment-0123")
    client = _signed_in(config_path)
    reference = "${IMMICH_API_KEY}|${IMMICH_MEMORIES_STORAGE_SECRET}"

    saved = client.post("/api/v1/settings", json={"values": {"auth.client_id": reference}})
    shown = client.get("/api/v1/settings")

    assert saved.status_code == 422
    for body in (saved.text, shown.text):
        assert "immich-key-from-the-environment-0123" not in body
        assert SIGNING_SECRET not in body


def test_the_settings_page_shows_auth_and_server_read_only(config_path):
    client = _signed_in(config_path)

    rows = {
        row["key"]: row
        for section in client.get("/api/v1/settings").json()["sections"]
        for row in section["settings"]
    }

    assert not any(row["editable"] for key, row in rows.items() if key.startswith("auth."))
    assert not any(row["editable"] for key, row in rows.items() if key.startswith("server."))


def test_a_stored_auth_or_server_setting_is_ignored_and_named_by_preflight(config_path):
    from immich_memories.preflight_settings import check_stored_settings

    _plant("server.trigger_token", "planted-token-0123456789abcdef0123456789")
    _plant("auth.enabled", True)

    config = get_config(reload=True)
    report = check_stored_settings(config)

    assert config.server.trigger_token == ""
    assert config.auth.enabled is False
    assert "server.trigger_token" in (report.details or "")
    assert "auth.enabled" in (report.details or "")
    assert "planted-token" not in str(report)


def test_config_yaml_still_expands_environment_variables(config_path):
    config_path.write_text("immich:\n  api_key: ${SOME_DEPLOYMENT_SECRET}\n")

    assert get_config(reload=True).immich.api_key == ENV_SECRET
