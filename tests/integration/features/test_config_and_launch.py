"""Setup contracts users script against: preflight's exit code, old config keys, --config, ui, auto install.

Each test runs the real CLI in a sealed home. The web server is `immich-memories ui` itself,
asked over HTTP the way the browser asks it.
"""

from __future__ import annotations

import re

import httpx
import pytest
import yaml

from immich_memories.config.loader import _REMOVED_CONFIG_KEYS, _REMOVED_TOP_LEVEL_SECTIONS
from immich_memories.config.models.render import _LEGACY_SCALE_MODES
from tests.features.cli_harness import UserHome, basic_config
from tests.integration.features.immich_server import LibraryServer
from tests.integration.features.served_ui import free_port, serve_ui

UNREACHABLE = "http://127.0.0.1:9"  # discard port: refused at once, no DNS


@pytest.fixture
def home(tmp_path) -> UserHome:
    return UserHome(tmp_path / "home")


# ── preflight ────────────────────────────────────────────────────────────────


@pytest.mark.feature("preflight.errors-exit-one")
def test_preflight_exits_one_and_names_the_fix_when_immich_cannot_be_reached(home: UserHome):
    home.write_config(basic_config(UNREACHABLE, "a-key-that-is-never-sent", home))

    # The scripted route stands in for `models fetch`, so Immich is the only failing check.
    result = home.run("preflight", scripted_selection=True)

    assert result.returncode == 1, result.explain()
    immich = re.search(r"│ Immich\s+│ (\w+)\s+│", result.stdout)
    assert immich and immich.group(1) == "ERROR", result.explain()
    assert "cannot reach 127.0.0.1:9" in result.stdout
    assert "rerun the same command once it does" in result.stdout
    assert "Preflight failed: 1 errors" in result.output
    assert "Fix the errors above before proceeding." in result.output


@pytest.mark.feature("preflight.errors-exit-one")
def test_preflight_exits_one_and_names_the_fix_for_a_rejected_api_key(
    home: UserHome, immich: LibraryServer
):
    home.write_config(basic_config(immich.base_url, "not-the-key-immich-issued", home))

    result = home.run("preflight", scripted_selection=True)

    assert result.returncode == 1, result.explain()
    immich = re.search(r"│ Immich\s+│ (\w+)\s+│", result.stdout)
    assert immich and immich.group(1) == "ERROR", result.explain()
    assert re.search(r"API key", result.stdout, re.I), result.explain()
    assert "Fix the errors above before proceeding." in result.output


# ── config compatibility ─────────────────────────────────────────────────────


def _with_every_retired_key(config: dict) -> dict:
    """The config plus every key and section the app has retired, each with a plausible value."""
    for key in _REMOVED_CONFIG_KEYS:
        section, _, field = key.partition(".")
        if field:
            config.setdefault(section, {})[field] = 1
        else:
            config[section] = {"enabled": True}
    for section in _REMOVED_TOP_LEVEL_SECTIONS:
        config[section] = {"weight": 1}
    return config


@pytest.mark.feature("config.deprecated-keys")
def test_every_retired_key_still_loads_and_its_warning_says_what_to_do(home: UserHome):
    home.write_config(_with_every_retired_key(basic_config(UNREACHABLE, "a-key", home)))

    result = home.run("config", "show")

    assert result.returncode == 0, result.explain()
    for key, reason in _REMOVED_CONFIG_KEYS.items():
        assert f"  {key}: {reason}" in result.stderr, key
    for section, reason in _REMOVED_TOP_LEVEL_SECTIONS.items():
        assert f"Ignoring config section '{section}' ({reason})" in result.stderr, section
    # The rest of the file still applies.
    assert re.search(r"│ output\.resolution\s+│ 720p\s+│ file", result.stdout), result.explain()


@pytest.mark.feature("config.deprecated-keys")
@pytest.mark.parametrize(("retired", "replacement"), sorted(_LEGACY_SCALE_MODES.items()))
def test_a_retired_scale_mode_runs_as_its_replacement_and_says_so(
    home: UserHome, retired: str, replacement: str
):
    config = basic_config(UNREACHABLE, "a-key", home)
    config["defaults"] = {"scale_mode": retired}
    home.write_config(config)

    result = home.run("config", "show")

    assert result.returncode == 0, result.explain()
    assert f"scale_mode '{retired}' no longer exists" in result.stderr
    assert f"Using '{replacement}'." in result.stderr
    assert re.search(rf"│ defaults\.scale_mode\s+│ {replacement}\s+│", result.stdout)


# ── --config ─────────────────────────────────────────────────────────────────

_USER = "feature-user"
_PASSWORD = "feature-password-long-enough"  # noqa: S105 -- a test login, not a secret


@pytest.mark.feature("config.global-config-flag")
def test_config_flag_picks_one_file_for_the_cli_the_ui_its_login_and_its_reloads(
    home: UserHome, tmp_path
):
    home.write_config(basic_config(UNREACHABLE, "a-key", home))  # the default file: 720p
    chosen = tmp_path / "elsewhere" / "chosen.yaml"
    chosen.parent.mkdir()
    config = basic_config(UNREACHABLE, "a-key", home)
    config["output"]["resolution"] = "1080p"
    config["auth"] = {
        "enabled": True,
        "provider": "basic",
        "username": _USER,
        "password": _PASSWORD,
    }
    chosen.write_text(yaml.safe_dump(config))
    chosen.chmod(0o600)
    port = free_port()

    shown = home.run("--config", str(chosen), "config", "show")
    with serve_ui(
        home, "--config", str(chosen), "ui", "--host", "127.0.0.1", "--port", str(port), port=port
    ):
        url = f"http://127.0.0.1:{port}"
        with httpx.Client(base_url=url, timeout=30) as browser:
            refused = browser.get("/api/v1/settings")
            signed_in = browser.post("/auth/login", json={"username": _USER, "password": _PASSWORD})
            before = browser.get("/api/v1/settings").json()
            config["output"]["resolution"] = "4k"
            chosen.write_text(yaml.safe_dump(config))
            after = browser.get("/api/v1/settings").json()

    assert shown.returncode == 0, shown.explain()
    assert re.search(r"│ output\.resolution\s+│ 1080p\s+│ file", shown.stdout), shown.explain()
    assert refused.status_code == 401
    assert signed_in.status_code == 200
    assert before["config_path"] == str(chosen)
    assert _setting(before, "output.resolution") == "1080p"
    assert _setting(after, "output.resolution") == "4k"


def _setting(view: dict, key: str) -> object:
    section = key.split(".", 1)[0]
    rows = next(s["settings"] for s in view["sections"] if s["name"] == section)
    return next(row["value"] for row in rows if row["key"] == key)


# ── ui ───────────────────────────────────────────────────────────────────────


@pytest.mark.feature("web.ui-launch")
def test_ui_binds_localhost_by_default_and_serves_the_web_client(home: UserHome):
    home.write_config(basic_config(UNREACHABLE, "a-key", home))
    home.turn_sign_in_off()  # this test is about the launch, not sign-in
    port = free_port()

    with serve_ui(home, "ui", "--port", str(port), port=port) as log:
        page = httpx.get(f"http://127.0.0.1:{port}/app/create", timeout=30)
        started = log.read_text()

    assert f"Starting Immich Memories UI on http://127.0.0.1:{port}" in started
    assert f"Uvicorn running on http://127.0.0.1:{port}" in started
    assert page.status_code == 200
    assert "<html" in page.text.lower()


@pytest.mark.feature("web.ui-launch")
def test_ui_host_and_reload_reach_the_server(home: UserHome):
    home.write_config(basic_config(UNREACHABLE, "a-key", home))
    port = free_port()

    with serve_ui(
        home, "ui", "--host", "localhost", "--port", str(port), "--reload", port=port
    ) as log:
        live = httpx.get(f"http://127.0.0.1:{port}/health/live", timeout=30)
        started = log.read_text()

    assert live.status_code == 200
    assert f"Uvicorn running on http://localhost:{port}" in started
    assert "Started reloader process" in started


# ── auto install ─────────────────────────────────────────────────────────────


def _schedule_of(text: str) -> tuple[int, int]:
    """(hour, minute) from whichever scheduler file this platform writes."""
    if launchd := re.search(
        r"<key>Hour</key>\s*<integer>(\d+)</integer>\s*<key>Minute</key>\s*<integer>(\d+)", text
    ):
        return int(launchd.group(1)), int(launchd.group(2))
    if systemd := re.search(r"OnCalendar=\*-\*-\* (\d\d):(\d\d)", text):
        return int(systemd.group(1)), int(systemd.group(2))
    cron = re.search(r"^(\d+) (\d+) \* \* \* ", text, re.M)
    assert cron, text
    return int(cron.group(2)), int(cron.group(1))


def _words(text: str) -> str:
    """The scheduler file with plist tags and shell quotes dropped, so argv reads as words."""
    return re.sub(r"<[^>]+>|['\"]", " ", text)


@pytest.mark.feature("scheduler.auto-install")
def test_auto_install_show_previews_the_schedule_and_installs_nothing(home: UserHome):
    config = basic_config(UNREACHABLE, "a-key", home)
    config["automation"] = {"cooldown_hours": 36}
    home.write_config(config)
    before = {p for p in home.root.rglob("*") if p.is_file()}

    preview = home.run("auto", "install", "--show", "--hour", "4", "--minute", "35")
    pinned = home.run("auto", "install", "--show", "--cooldown", "12")
    status = home.run("auto", "status")
    written = {p for p in home.root.rglob("*") if p.is_file()} - before

    assert preview.returncode == 0, preview.explain()
    assert _schedule_of(preview.stdout) == (4, 35)
    launcher = home.root / ".immich-memories" / "bin" / "immich-memories-auto"
    assert str(launcher) in preview.stdout
    assert re.search(r"\bauto\s+run\b", _words(preview.stdout)), preview.explain()
    # Without --cooldown the run reads automation.cooldown_hours each time, so none is pinned.
    assert "--cooldown" not in preview.stdout
    assert "Cooldown: ready (36h)" in status.stdout, status.explain()
    assert _schedule_of(pinned.stdout) == (9, 0)
    assert re.search(r"--cooldown\s+12\b", _words(pinned.stdout)), pinned.explain()
    # --show wrote no launcher, no scheduler file, and activated nothing.
    assert not launcher.exists()
    scheduler_files = [
        p for p in written if p.suffix in {".plist", ".service", ".timer"} or "cron" in p.name
    ]
    assert scheduler_files == []
