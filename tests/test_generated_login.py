"""Authentication is on by default: a fresh install generates its password and logs it once."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from immich_memories.config.loader import Config
from immich_memories.web.generated_login import LOGIN_FILE
from tests.web_server_fixtures import server_client

LAN = ("192.168.1.50", 50000)


@pytest.fixture
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The folder of the config file, where the generated login is kept."""
    config_dir = tmp_path / ".immich-memories"
    config_dir.mkdir()
    # WHY: the login file sits beside the config file; this run's config is a temp one.
    monkeypatch.setattr("immich_memories.config.loader._config_path", config_dir / "config.yaml")
    return config_dir


def _shown_password(caplog: pytest.LogCaptureFixture) -> str:
    lines = [r.getMessage() for r in caplog.records if "password:" in r.getMessage()]
    assert len(lines) == 1, lines
    return lines[0].split("password: ")[1].split()[0]


def _sign_in(client, password: str, username: str = "admin"):
    return client.post("/auth/login", json={"username": username, "password": password})


def test_a_default_config_asks_for_sign_in():
    assert Config().auth.enabled
    assert Config().auth.generates_login


def test_first_start_generates_a_password_and_logs_it_once(state_dir, monkeypatch, caplog):
    caplog.set_level(logging.INFO)

    client = server_client(monkeypatch, Config())

    password = _shown_password(caplog)
    assert password not in (state_dir / LOGIN_FILE).read_text()
    assert client.get("/api/v1/session").json()["generated_login"] is True
    assert _sign_in(client, password).status_code == 200
    assert client.get("/api/v1/runs").status_code != 401


def _plain_get_routes(client) -> list[str]:
    return sorted(
        route.path
        for route in client.app.routes
        if "GET" in getattr(route, "methods", ()) and "{" not in route.path
    )


def test_no_http_route_ever_returns_the_password(state_dir, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    client = server_client(monkeypatch, Config(), client=LAN)
    password = _shown_password(caplog)

    for path in [*_plain_get_routes(client), "/api/v1/session/first-login"]:
        for host in ("localhost", "memories.example.org"):
            answer = client.get(path, headers={"host": host})
            assert password not in answer.text, path
    assert _sign_in(client, password).status_code == 200
    for path in ("/api/v1/session", "/api/v1/settings", "/health", "/app/login"):
        assert password not in client.get(path, headers={"host": "localhost"}).text, path


def test_a_request_without_the_password_is_refused_even_naming_localhost(state_dir, monkeypatch):
    client = server_client(monkeypatch, Config(), client=LAN)

    refused = client.get("/api/v1/runs", headers={"host": "localhost"})
    wrong = _sign_in(client, "not-the-password")

    assert refused.status_code == 401
    assert wrong.status_code == 401


def test_explicitly_disabled_auth_still_serves(state_dir, monkeypatch):
    client = server_client(monkeypatch, Config(auth={"enabled": False}))

    assert client.get("/api/v1/session").json()["auth_enabled"] is False
    assert client.get("/api/v1/session").json()["generated_login"] is False
    assert not (state_dir / LOGIN_FILE).exists()


def test_configured_credentials_generate_nothing(state_dir, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    config = Config(auth={"username": "operator", "password": "a-long-chosen-password"})

    client = server_client(monkeypatch, config)

    assert not (state_dir / LOGIN_FILE).exists()
    assert not [r for r in caplog.records if "password:" in r.getMessage()]
    assert _sign_in(client, "a-long-chosen-password", "operator").status_code == 200


def test_the_password_survives_a_restart_and_is_never_shown_again(state_dir, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    server_client(monkeypatch, Config())
    password = _shown_password(caplog)
    caplog.clear()

    restarted = server_client(monkeypatch, Config())

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert password not in logged
    assert _sign_in(restarted, password).status_code == 200


def _reset(state_dir: Path):
    from immich_memories.cli import main

    config = state_dir / "config.yaml"
    if not config.exists():
        config.write_text("immich:\n  url: http://immich.test\n")
    return CliRunner().invoke(main, ["--config", str(config), "auth", "reset-password"])


def test_reset_password_prints_a_new_one_and_ends_the_old_sessions(state_dir, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    client = server_client(monkeypatch, Config())
    old = _shown_password(caplog)
    assert _sign_in(client, old).status_code == 200

    reset = _reset(state_dir)

    assert reset.exit_code == 0, reset.output
    new = reset.output.split("password: ")[1].split()[0]
    assert new != old
    assert new not in (state_dir / LOGIN_FILE).read_text()
    assert client.get("/api/v1/runs").status_code == 401
    assert _sign_in(client, old).status_code == 401
    assert _sign_in(client, new).status_code == 200


def test_reset_password_refuses_a_configured_password(state_dir):
    (state_dir / "config.yaml").write_text(
        "advanced:\n  auth:\n    username: operator\n    password: a-long-chosen-password\n"
    )

    reset = _reset(state_dir)

    assert reset.exit_code == 1
    assert not (state_dir / LOGIN_FILE).exists()


def test_config_output_never_carries_the_password(state_dir, monkeypatch, caplog):
    from immich_memories.cli import main

    caplog.set_level(logging.INFO)
    server_client(monkeypatch, Config())
    password = _shown_password(caplog)
    (state_dir / "config.yaml").write_text("immich:\n  url: http://immich.test\n")

    shown = CliRunner().invoke(main, ["--config", str(state_dir / "config.yaml"), "config", "show"])

    assert shown.exit_code == 0, shown.output
    assert password not in shown.output


# A worker process: say it is ready, wait for the go file so every worker starts together,
# then do what a server start does, with the log on stderr.
_WORKER = """
import logging, os, sys, time
from pathlib import Path
from immich_memories.config.models.auth import AuthConfig
from immich_memories.web.generated_login import announce_generated_login
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
state_dir, go = Path(sys.argv[1]), Path(sys.argv[2])
(go.parent / f"ready-{os.getpid()}").touch()
while not go.exists():
    time.sleep(0.001)
announce_generated_login(AuthConfig(), state_dir)
"""


def test_workers_starting_together_share_one_password_and_only_one_logs_it(tmp_path):
    import subprocess
    import sys

    from immich_memories.config.models.auth import AuthConfig
    from immich_memories.web.generated_login import generated_credentials_match, login_path

    state_dir, go = tmp_path / "state", tmp_path / "go"
    state_dir.mkdir(mode=0o700)
    workers = [
        subprocess.Popen(
            [sys.executable, "-c", _WORKER, str(state_dir), str(go)],
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(6)
    ]
    deadline = time.monotonic() + 60
    while len(list(tmp_path.glob("ready-*"))) < len(workers) and time.monotonic() < deadline:
        time.sleep(0.05)
    go.touch()
    logs = [worker.communicate(timeout=60)[1] for worker in workers]

    assert all(worker.returncode == 0 for worker in workers), logs
    shown = [log.split("password: ")[1].split()[0] for log in logs if "password: " in log]
    assert len(shown) == 1, logs
    assert generated_credentials_match("admin", shown[0], AuthConfig(), login_path(state_dir))


def test_an_unreadable_login_file_is_kept_aside_and_the_warning_says_so(
    state_dir, monkeypatch, caplog
):
    caplog.set_level(logging.INFO)
    (state_dir / LOGIN_FILE).write_text('{"salt": "truncat')

    client = server_client(monkeypatch, Config())

    password = _shown_password(caplog)
    kept = list(state_dir.glob(f"{LOGIN_FILE}.corrupt-*"))
    assert len(kept) == 1
    assert kept[0].read_text() == '{"salt": "truncat'
    warning = next(r for r in caplog.records if "could not be read" in r.getMessage())
    assert warning.levelno == logging.WARNING
    said = warning.getMessage()
    assert kept[0].name in said
    assert "new password" in said
    assert "immich-memories auth reset-password" in said
    assert password not in said
    assert _sign_in(client, password).status_code == 200
