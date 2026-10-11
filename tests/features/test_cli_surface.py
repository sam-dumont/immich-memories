"""Feature tests for what the CLI prints before it touches a library.

The real CLI runs as a child process in a sealed home; nothing here reaches a network
(the configured Immich address is reserved and never answers).
"""

from __future__ import annotations

import re
import subprocess
import sys

import pytest

import immich_memories
from tests.features.cli_harness import OutboundTrap, UserHome, basic_config

# Every secret-bearing setting holds a sentinel; none may come back in anything printed.
SECRETS = {
    "immich": "FEATURE-SECRET-IMMICH-KEY-7f3a",
    "account": "FEATURE-SECRET-ACCOUNT-KEY-91c2",
    "llm": "FEATURE-SECRET-LLM-KEY-5d0e",
    "password": "FEATURE-SECRET-PASSWORD-2b6f",
    "notify": "FEATURE-SECRET-NOTIFY-TOKEN-c48d",
    "trigger": "FEATURE-SECRET-TRIGGER-TOKEN-0a1b2c3d4e5f6a7b",
}
UNREACHABLE = "http://127.0.0.1:9"  # discard port: refused at once, no DNS


def _secret_config(home: UserHome) -> dict:
    config = basic_config(UNREACHABLE, SECRETS["immich"], home)
    config["immich"]["accounts"] = {"partner": {"url": UNREACHABLE, "api_key": SECRETS["account"]}}
    config["advanced"] |= {
        "llm": {"enabled": False, "api_key": SECRETS["llm"]},
        "auth": {
            "enabled": True,
            "provider": "basic",
            "username": "admin",
            "password": SECRETS["password"],
        },
        "notifications": {
            "enabled": False,
            "urls": [f"json://user:{SECRETS['notify']}@notify.invalid"],
        },
        "server": {"trigger_token": SECRETS["trigger"]},
    }
    return config


def _leaks(text: str) -> list[str]:
    # A head or a tail counts: pydantic elides the middle of a long input, never its ends.
    return [name for name, value in SECRETS.items() if value[:14] in text or value[-10:] in text]


@pytest.fixture
def home(tmp_path) -> UserHome:
    return UserHome(tmp_path / "home")


@pytest.mark.feature("cli.version")
def test_version_prints_the_installed_version(home):
    result = home.run("--version")

    assert result.returncode == 0, result.explain()
    assert immich_memories.__version__ in result.stdout


@pytest.mark.feature("config.show-redacts-secrets")
@pytest.mark.parametrize("command", [("config", "show"), ("config", "--show")])
def test_config_show_lists_settings_without_their_secrets(home, command):
    home.write_config(_secret_config(home))

    result = home.run(*command)

    assert result.returncode == 0, result.explain()
    assert "immich.api_key" in result.stdout
    assert "immich.url" in result.stdout
    assert _leaks(result.output) == []


def _full_tier_without_a_reader(config: dict) -> None:
    config["tier"] = "full"


def _unknown_notification_scheme(config: dict) -> None:
    config["advanced"]["notifications"]["urls"] = [f"nosuch://{SECRETS['notify']}@host"]


def _secret_under_an_unknown_key(config: dict) -> None:
    config["advanced"]["auth"]["secret_token"] = SECRETS["password"]


def _account_url_carrying_its_key(config: dict) -> None:
    config["immich"]["accounts"]["partner"]["url"] = f"ftp://{SECRETS['account']}@host"


def _api_key_of_the_wrong_type(config: dict) -> None:
    config["immich"]["api_key"] = [SECRETS["immich"]]


# Each breakage meets a different entry point, so five child runs cover every path a
# config error takes to the terminal: the preflight table, verbose logging, the settings
# listing, a generate plan and a store read.
BROKEN = [
    (_full_tier_without_a_reader, ("-v", "preflight")),
    (_unknown_notification_scheme, ("config", "test")),
    (_secret_under_an_unknown_key, ("config", "show")),
    (_account_url_carrying_its_key, ("generate", "--year", "2024", "--dry-run")),
    (_api_key_of_the_wrong_type, ("runs", "list")),
]


@pytest.mark.feature("privacy.config-errors-hide-secrets")
@pytest.mark.parametrize(
    ("breakage", "command"), BROKEN, ids=[f.__name__.strip("_") for f, _ in BROKEN]
)
def test_a_config_error_names_the_problem_and_prints_no_secret(home, breakage, command):
    config = _secret_config(home)
    breakage(config)
    home.write_config(config)

    result = home.run(*command)

    assert result.returncode != 0, result.explain()
    assert "error" in result.output.lower(), result.explain()
    assert _leaks(result.output) == [], result.explain()


def test_the_outbound_trap_catches_a_call_that_leaves_the_machine(tmp_path):
    # Guards privacy.immich-only-by-default: an empty trap must mean nothing tried.
    trap = OutboundTrap()
    try:
        home = UserHome(tmp_path / "home", extra_env=tuple(trap.env().items()))
        probe = "import httpx\ntry:\n    httpx.get('https://example.org/', timeout=3)\nexcept Exception:\n    pass\n"
        subprocess.run(  # noqa: S603 -- fixed argv
            [sys.executable, "-c", probe], env=home.env(), check=True, timeout=30
        )
    finally:
        trap.close()

    assert trap.requests == ["CONNECT example.org:443 HTTP/1.1"]


def _setting(output: str, key: str) -> tuple[str, str]:
    """The value and source `config show` prints for one key (wide terminal, one line)."""
    row = re.search(rf"│\s*{re.escape(key)}\s*│\s*(.*?)\s*│\s*(\w+)\s*│", output)
    assert row, output[-3000:]
    return row.group(1), row.group(2)


@pytest.mark.feature("config.env-pattern")
@pytest.mark.feature("config.precedence")
def test_an_environment_variable_sets_a_key_and_wins_over_the_file(home):
    home.write_config(basic_config(UNREACHABLE, SECRETS["immich"], home))

    from_file = home.run("config", "show")
    from_env = home.run(
        "config",
        "show",
        env={
            "IMMICH_MEMORIES_OUTPUT__RESOLUTION": "1080p",
            # A tier-2 key: no ADVANCED prefix, and a list as JSON.
            "IMMICH_MEMORIES_ANALYSIS__EXCLUDE_FILENAME_PATTERNS": '["RingVideo_*", "Screenshot*"]',
        },
    )

    assert _setting(from_file.stdout, "output.resolution") == ("720p", "file")
    assert _setting(from_env.stdout, "output.resolution") == ("1080p", "env")
    assert _setting(from_env.stdout, "analysis.exclude_filename_patterns") == (
        '["RingVideo_*", "Screenshot*"]',
        "env",
    )


@pytest.mark.feature("config.invalid-shape")
@pytest.mark.parametrize(
    ("text", "accepted"),
    [
        ("- a\n- b\n", False),
        ("42\n", False),
        ("", True),
        # A misspelled authentication switch must not silently leave authentication off.
        ("advanced:\n  auth:\n    enabeld: true\n", False),
    ],
    ids=["list", "scalar", "empty", "misspelled-auth-key"],
)
def test_a_config_must_be_a_mapping_and_an_empty_one_changes_nothing(home, text, accepted):
    home.config_path.parent.mkdir(parents=True, exist_ok=True)
    home.config_path.write_text(text)

    result = home.run("config", "show")

    assert (result.returncode == 0) is accepted, result.explain()
    if not accepted and "auth" not in text:
        assert "must be a mapping of setting names to values" in result.output, result.explain()
        assert "YAML syntax error" not in result.output
    elif not accepted:
        assert "error" in result.output.lower(), result.explain()


@pytest.mark.feature("runs.unknown-id-fails")
@pytest.mark.parametrize("command", [("runs", "show"), ("runs", "delete", "--yes")])
def test_an_unknown_run_id_says_so_and_exits_non_zero(home, command):
    home.write_config(basic_config(UNREACHABLE, SECRETS["immich"], home))

    result = home.run(*command, "20240101_000000_dead")

    assert result.returncode == 1, result.explain()
    assert "Run not found: 20240101_000000_dead" in result.output
