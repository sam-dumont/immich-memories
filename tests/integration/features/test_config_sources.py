"""Where a setting comes from: the five sources, saving to the database, shorthands, tiers and preflight.

Each test runs the real CLI in a sealed home; Settings is `immich-memories ui` asked over
HTTP the way the browser asks it. What the tests read is what a user reads: `config show`'s
value and source columns, an exit code, a refusal, or a command that only works when the
connection it was given is the one in use.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
import pytest
import yaml

from tests.features.cli_harness import CliResult, OutboundTrap, UserHome, basic_config
from tests.integration.features.immich_server import LibraryServer
from tests.integration.features.served_ui import free_port, serve_ui

UNREACHABLE = "http://127.0.0.1:9"  # discard port: refused at once, no DNS
# A sentinel only a test would hold; it must never come back in anything printed.
SENTINEL_KEY = "FEATURE-SENTINEL-KEY-6c1d"  # noqa: S105 -- a test sentinel, not a secret
SECRET_KEY = "feature-secret-key-for-the-store-0123456789abcdef"  # noqa: S105 -- test only


@pytest.fixture
def home(tmp_path) -> UserHome:
    return UserHome(tmp_path / "home")


def _row(result: CliResult, key: str) -> tuple[str, str, str]:
    """`config show`'s (value, source, set by) for one key."""
    row = re.search(rf"^│ {re.escape(key)}\s+│ (.*?)\s+│ (\w+)\s+│ (.*?)\s*│$", result.stdout, re.M)
    assert row, f"no row for {key}\n{result.explain()}"
    return row.group(1), row.group(2), row.group(3)


def _without_immich(home: UserHome) -> dict:
    """A Basic install whose config.yaml names no Immich, so a saved connection is the one used."""
    config = basic_config(UNREACHABLE, "unused", home)
    del config["immich"]
    return config


@contextmanager
def _settings_page(home: UserHome, **env: str) -> Iterator[httpx.Client]:
    """`immich-memories ui` on this home, and a client asking its Settings API."""
    port = free_port()
    served = UserHome(home.root, extra_env=(*home.extra_env, *env.items()))
    with (
        serve_ui(served, "ui", "--port", str(port), port=port),
        httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30) as client,
    ):
        yield client


def _setting(view: dict, key: str) -> dict:
    section = key.split(".", 1)[0]
    rows = next(s["settings"] for s in view["sections"] if s["name"] == section)
    return next(row for row in rows if row["key"] == key)


# ── saving a connection, and the secret key it needs ─────────────────────────


@pytest.mark.feature("config.set-connection")
def test_config_url_and_api_key_save_the_connection_the_next_command_uses(
    home: UserHome, immich: LibraryServer
):
    home.write_config(_without_immich(home))
    with_key = {"IMMICH_MEMORIES_SECRET_KEY": SECRET_KEY}

    saved = home.run("config", "--url", immich.base_url, "--api-key", immich.api_key, env=with_key)
    shown = home.run("config", "show", "immich", env=with_key)
    years = home.run("years", env=with_key)

    assert saved.returncode == 0, saved.explain()
    assert "Saved to the database: immich.api_key, immich.url" in saved.output
    assert _row(shown, "immich.url")[:2] == (immich.base_url, "database")
    assert _row(shown, "immich.api_key")[:2] == ("***", "database")
    assert immich.api_key not in shown.output
    # config.yaml was never written: the file still names no Immich.
    assert "immich" not in yaml.safe_load(home.config_path.read_text())
    assert years.returncode == 0, years.explain()
    assert "2025" in years.stdout


@pytest.mark.feature("config.secrets-in-db")
def test_saving_a_credential_without_the_secret_key_is_refused_in_the_cli_and_settings(
    home: UserHome,
):
    home.write_config(_without_immich(home))

    refused = home.run("config", "--url", UNREACHABLE, "--api-key", SENTINEL_KEY)
    shown = home.run("config", "show", "immich")
    with _settings_page(home) as settings:
        page = settings.get("/api/v1/settings")
        posted = settings.post("/api/v1/settings", json={"values": {"llm.api_key": SENTINEL_KEY}})
        after = settings.get("/api/v1/settings").json()

    assert refused.returncode == 1, refused.explain()
    assert "IMMICH_MEMORIES_SECRET_KEY" in refused.output
    assert SENTINEL_KEY not in refused.output
    assert "IMMICH_MEMORIES_SECRET_KEY: not set (secrets cannot be saved)" in shown.stdout
    # Nothing was saved, not even the URL that came with the key.
    assert _row(shown, "immich.url")[1] == "default"
    assert _row(shown, "immich.api_key")[1] == "default"
    assert page.json()["can_store_secrets"] is False
    assert _setting(page.json(), "llm.api_key")["editable"] is False
    assert posted.status_code == 422, posted.text
    assert "IMMICH_MEMORIES_SECRET_KEY" in posted.text
    assert SENTINEL_KEY not in posted.text
    assert _setting(after, "llm.api_key")["source"] == "default"


# ── ${VAR} in config.yaml, refused in Settings ───────────────────────────────


@pytest.mark.feature("config.var-substitution")
def test_braced_variables_fill_credentials_and_service_fields_and_settings_refuses_them(
    home: UserHome, immich: LibraryServer
):
    config = basic_config("${FEATURE_IMMICH_URL}", "${FEATURE_IMMICH_KEY}", home)
    # A field outside the substitution list keeps the text as written.
    config["output"]["directory"] = "${FEATURE_IMMICH_URL}"
    home.write_config(config)
    env = {"FEATURE_IMMICH_URL": immich.base_url, "FEATURE_IMMICH_KEY": immich.api_key}
    served = UserHome(home.root, extra_env=tuple(env.items()))

    years = served.run("years")
    shown = served.run("config", "show", "immich.url", "output.directory")
    # The config CLI refuses it too, on a key config.yaml leaves to it.
    bare = UserHome(home.root.parent / "bare", extra_env=tuple(env.items()))
    bare.write_config(_without_immich(bare))
    refused = bare.run("config", "--url", "${FEATURE_IMMICH_URL}")
    left = bare.run("config", "show", "immich.url")
    with _settings_page(served) as settings:
        posted = settings.post("/api/v1/settings", json={"values": {"llm.model": "${FEATURE_X}"}})

    assert years.returncode == 0, years.explain()
    assert "2025" in years.stdout
    assert _row(shown, "immich.url")[:2] == (immich.base_url, "file")
    assert _row(shown, "output.directory")[0] == "${FEATURE_IMMICH_URL}"
    assert refused.returncode == 1, refused.explain()
    assert "Settings can't reference environment variables" in refused.output
    assert _row(left, "immich.url")[1] == "default"
    assert posted.status_code == 422, posted.text
    assert "can't reference environment variables" in posted.text


# ── move-to-db ───────────────────────────────────────────────────────────────


@pytest.mark.feature("config.move-to-db")
def test_move_to_db_hands_named_keys_to_settings_and_keeps_the_rest_of_the_file(home: UserHome):
    config = basic_config(UNREACHABLE, "a-key", home)
    config["advanced"]["llm"] = {"model": "moved-model"}
    config["automation"] = {"cooldown_hours": 30}
    home.write_config(config)

    moved = home.run("config", "move-to-db", "llm.model", "automation.cooldown_hours")
    left = yaml.safe_load(home.config_path.read_text())
    shown = home.run(
        "config", "show", "llm.model", "automation.cooldown_hours", "output.resolution"
    )
    with _settings_page(home) as settings:
        before = settings.get("/api/v1/settings").json()
        saved = settings.post("/api/v1/settings", json={"values": {"llm.model": "edited-model"}})
    edited = home.run("config", "show", "llm.model")

    assert moved.returncode == 0, moved.explain()
    assert "Moved to the database: llm.model, automation.cooldown_hours" in moved.output
    assert home.config_path.with_name("config.yaml.bak").is_file()
    assert "llm" not in left["advanced"]
    assert "automation" not in left
    assert left["output"]["resolution"] == "720p"
    assert _row(shown, "llm.model")[:2] == ("moved-model", "database")
    assert _row(shown, "automation.cooldown_hours")[:2] == ("30", "database")
    assert _row(shown, "output.resolution")[1] == "file"
    # Settings controls the key now: editable there, and its save is what the CLI reads.
    assert _setting(before, "llm.model")["editable"] is True
    assert saved.status_code == 200, saved.text
    assert _row(edited, "llm.model")[:2] == ("edited-model", "database")


# ── the order of the sources ─────────────────────────────────────────────────


@pytest.mark.feature("config.precedence-full-order")
def test_each_source_wins_over_every_source_below_it(home: UserHome):
    config = basic_config(UNREACHABLE, "a-key", home)
    home.write_config(config)
    deployment = {"IMMICH_MEMORIES_DEPLOYMENT_READER_MODEL": "deployment-model"}

    def model(**env: str) -> tuple[str, str, str]:
        result = home.run("config", "show", "llm.model", env=env)
        assert result.returncode == 0, result.explain()
        return _row(result, "llm.model")

    built_in = model()
    deployed = model(**deployment)
    config["advanced"]["llm"] = {"model": "settings-model"}
    home.write_config(config)
    moved = home.run("config", "move-to-db", "llm.model")
    assert moved.returncode == 0, moved.explain()
    from_settings = model(**deployment)
    config["advanced"]["llm"] = {"model": "file-model"}
    home.write_config(config)
    from_file = model(**deployment)
    from_env = model(**deployment, IMMICH_MEMORIES_LLM__MODEL="env-model")

    assert built_in[1] == "default"
    assert built_in[0] not in {"deployment-model", "settings-model", "file-model", "env-model"}
    # A deployment default is still a default: it only replaces the built-in value.
    assert deployed[:2] == ("deployment-model", "default")
    assert from_settings[:2] == ("settings-model", "database")
    assert from_file[:2] == ("file-model", "file")
    assert from_env == ("env-model", "env", "IMMICH_MEMORIES_LLM__MODEL")


@pytest.mark.feature("config.env-shorthands")
def test_immich_shorthands_beat_the_nested_variables_and_basic_auth_needs_both(
    home: UserHome, immich: LibraryServer
):
    home.write_config(_without_immich(home))
    nested = {"IMMICH_MEMORIES_IMMICH__URL": UNREACHABLE, "IMMICH_MEMORIES_IMMICH__API_KEY": "x"}
    shorthand = {"IMMICH_URL": immich.base_url, "IMMICH_API_KEY": immich.api_key}

    shown = home.run("config", "show", "immich", env=nested | shorthand)
    years = home.run("years", env=nested | shorthand)
    half = home.run("config", "show", "auth", env={"IMMICH_MEMORIES_AUTH_USERNAME": "kit"})
    both = home.run(
        "config",
        "show",
        "auth",
        env={
            "IMMICH_MEMORIES_AUTH_USERNAME": "kit",
            "IMMICH_MEMORIES_AUTH_PASSWORD": "a-long-enough-password",
        },
    )

    assert _row(shown, "immich.url") == (immich.base_url, "env", "IMMICH_URL")
    assert _row(shown, "immich.api_key")[1:] == ("env", "IMMICH_API_KEY")
    assert years.returncode == 0, years.explain()
    assert "2025" in years.stdout
    # One Basic-auth value alone is ignored; the pair turns sign-in on.
    assert _row(half, "auth.enabled")[:2] == ("false", "default")
    assert _row(both, "auth.enabled")[:2] == ("true", "env")
    assert _row(both, "auth.provider")[0] == "basic"
    assert _row(both, "auth.username")[0] == "kit"


# ── tier ─────────────────────────────────────────────────────────────────────


def _selection_tier(home: UserHome, **env: str) -> str:
    result = home.run("capabilities", "--json", env=env)
    tier = re.search(r'"Selection tier: (\w+)"', result.stdout)
    assert tier, result.explain()
    return tier.group(1)


@pytest.mark.feature("config.tiers")
def test_tier_chooses_the_compute_tier_and_the_deployment_default_yields_to_yaml_and_settings(
    home: UserHome,
):
    config = basic_config(UNREACHABLE, "a-key", home)
    # Loopback service addresses, so a GPU-tier probe is refused at once and leaves no trace.
    config["advanced"]["inference"] = {"facts_base_url": UNREACHABLE}
    config["advanced"]["editorial"] = {"preparation": {"caption_base_url": f"{UNREACHABLE}/v1"}}
    deployment = {"IMMICH_MEMORIES_DEPLOYMENT_TIER": "gpu"}
    del config["tier"]
    home.write_config(config)

    deployed = _selection_tier(home, **deployment)
    deployed_row = _row(home.run("config", "show", "tier", env=deployment), "tier")
    config["tier"] = "basic"
    home.write_config(config)
    in_yaml = _selection_tier(home, **deployment)
    moved = home.run("config", "move-to-db", "tier", env=deployment)
    in_settings = _row(home.run("config", "show", "tier", env=deployment), "tier")
    settings_tier = _selection_tier(home, **deployment)

    assert deployed == "gpu"
    assert deployed_row[:2] == ("gpu", "default")
    assert in_yaml == "basic"
    assert moved.returncode == 0, moved.explain()
    assert in_settings[:2] == ("basic", "database")
    assert settings_tier == "basic"


# ── -v and --log-level ───────────────────────────────────────────────────────


@pytest.mark.feature("config.log-level")
def test_verbose_and_log_level_debug_turn_on_debug_logs_for_a_command(
    home: UserHome, immich: LibraryServer
):
    home.write_config(basic_config(immich.base_url, immich.api_key, home))

    plain = home.run("years")
    verbose = home.run("-v", "years")
    debug = home.run("--log-level", "DEBUG", "years")

    for result in (plain, verbose, debug):
        assert result.returncode == 0, result.explain()
    assert "[DEBUG]" not in plain.output
    for result in (verbose, debug):
        assert re.search(r"\[DEBUG\] immich_memories\.api\.immich .*Request: GET", result.stderr), (
            result.explain()
        )


# ── preflight ────────────────────────────────────────────────────────────────


@pytest.mark.feature("preflight.outside-calls")
def test_preflight_names_every_enabled_outside_destination_and_none_by_default(
    home: UserHome, immich: LibraryServer, outbound_trap: OutboundTrap
):
    trapped = UserHome(home.root, extra_env=tuple(outbound_trap.env().items()))
    config = basic_config(immich.base_url, immich.api_key, trapped)
    trapped.write_config(config)
    default = trapped.run("preflight", scripted_selection=True)
    config["network"] = {"geocoding": True, "map_tiles": True}
    trapped.write_config(config)
    public = trapped.run("preflight", scripted_selection=True)
    config["network"]["geocoding_url"] = "http://127.0.0.1:9/nominatim"
    trapped.write_config(config)
    self_hosted = trapped.run("preflight", scripted_selection=True)

    def outside(result: CliResult) -> dict[str, str]:
        return dict(re.findall(r"│ Outside call: (\w+)\s+│ \w+\s+│ (\S+) will be", result.stdout))

    assert outside(default) == {}, default.explain()
    assert outside(public) == {
        "geocoding": "nominatim.openstreetmap.org",
        "map_tiles": "server.arcgisonline.com",
    }, public.explain()
    # A self-hosted Nominatim is the host the run reaches, so it is the one named.
    assert outside(self_hosted)["geocoding"] == "http://127.0.0.1:9/nominatim"


_SHORT_WARNING = "auth.password is shorter than 12 characters"


@pytest.mark.feature("preflight.weak-password-warning")
@pytest.mark.parametrize(("password", "warned"), [("short-pw", True), ("long-enough-pw", False)])
def test_a_basic_auth_password_under_twelve_characters_warns_at_preflight_and_startup(
    home: UserHome, password: str, warned: bool
):
    config = basic_config(UNREACHABLE, "a-key", home)
    config["auth"] = {"enabled": True, "provider": "basic", "username": "kit", "password": password}
    home.write_config(config)
    port = free_port()

    checked = home.run("preflight", scripted_selection=True)
    with serve_ui(home, "ui", "--port", str(port), port=port) as log:
        started = log.read_text()

    sign_in = re.search(r"│ Sign-in\s+│ (\w+)\s+│ ([^│]*)│", checked.stdout)
    assert sign_in, checked.explain()
    assert (sign_in.group(1) == "WARNING") is warned, checked.explain()
    assert (_SHORT_WARNING in sign_in.group(2)) is warned
    assert (_SHORT_WARNING in started) is warned, started[-3000:]
    assert password not in checked.output
    assert password not in started
