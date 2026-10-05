"""No config error path may print a secret value (#2129).

Every secret-bearing field holds a sentinel; each broken config below is loaded through
the CLI and through a raw traceback, and no sentinel may appear in what comes out.
"""

from __future__ import annotations

import traceback
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from immich_memories.cli import main
from immich_memories.config_loader import Config

SENTINELS = {
    "immich": "SENTINEL-IMMICH-KEY-0001",
    "account": "SENTINEL-ACCOUNT-KEY-0002",
    "llm": "SENTINEL-LLM-KEY-0003",
    "musicgen": "SENTINEL-MUSICGEN-KEY-0004",
    "ace": "SENTINEL-ACE-KEY-0005",
    "password": "SENTINEL-PASSWORD-0006",
    "oidc": "SENTINEL-OIDC-SECRET-0007",
    "notify": "SENTINEL-NOTIFY-TOKEN-0008",
    "trigger": "SENTINEL-TRIGGER-TOKEN-0009-padded-to-32-chars",
    "worker": "SENTINEL-WORKER-TOKEN-0010",
    "caption": "SENTINEL-CAPTION-KEY-0011",
}


def _secret_config() -> dict:
    return {
        "tier": "gpu",
        "immich": {
            "url": "http://immich.invalid:2283",
            "api_key": SENTINELS["immich"],
            "accounts": {
                "second": {"url": "http://immich.invalid:2283", "api_key": SENTINELS["account"]}
            },
        },
        "render": {"worker_token": SENTINELS["worker"]},
        "advanced": {
            "llm": {"enabled": False, "api_key": SENTINELS["llm"]},
            "musicgen": {"api_key": SENTINELS["musicgen"]},
            "ace_step": {"api_key": SENTINELS["ace"]},
            "auth": {
                "enabled": True,
                "provider": "oidc",
                "password": SENTINELS["password"],
                "issuer_url": "https://idp.invalid",
                "client_id": "app",
                "client_secret": SENTINELS["oidc"],
            },
            "notifications": {
                "urls": [f"json://user:{SENTINELS['notify']}@notify.invalid"],
            },
            "server": {"trigger_token": SENTINELS["trigger"]},
            "editorial": {"preparation": {"caption_api_key": SENTINELS["caption"]}},
        },
    }


def _full_tier_without_llm(data: dict) -> None:
    data["tier"] = "full"


def _unsupported_notification_url(data: dict) -> None:
    data["advanced"]["notifications"]["urls"] = [f"nosuch://{SENTINELS['notify']}@host"]


def _unknown_auth_key(data: dict) -> None:
    data["advanced"]["auth"]["secret_token"] = SENTINELS["password"]


def _bad_account_url(data: dict) -> None:
    data["immich"]["accounts"]["second"]["url"] = f"ftp://{SENTINELS['account']}@host"


BROKEN = [
    _full_tier_without_llm,
    _unsupported_notification_url,
    _unknown_auth_key,
    _bad_account_url,
]


def _write(tmp_path: Path, breakage) -> Path:
    data = _secret_config()
    breakage(data)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def _leaked(text: str) -> list[str]:
    # A tail counts too: pydantic elides the middle of a long input, never its ends.
    return [value for value in SENTINELS.values() if value[:12] in text or value[-12:] in text]


def test_the_sentinel_config_itself_loads(tmp_path):
    # Guards the test: each broken variant below fails for its one breakage only.
    Config.from_yaml(_write(tmp_path, lambda _data: None))


@pytest.mark.parametrize("breakage", BROKEN, ids=lambda f: f.__name__.strip("_"))
@pytest.mark.parametrize("command", [["preflight"], ["config", "test"], ["config", "show"]])
def test_a_config_error_on_the_cli_prints_no_secret(tmp_path, breakage, command):
    path = _write(tmp_path, breakage)

    # WHY: the real init creates ~/.immich-memories; this run must not touch a home dir.
    with patch("immich_memories.cli.init_config_dir"):
        result = CliRunner().invoke(main, ["-c", str(path), *command])

    assert result.exit_code == 1
    assert "Configuration error" in result.output
    assert _leaked(result.output) == []


@pytest.mark.parametrize("breakage", BROKEN, ids=lambda f: f.__name__.strip("_"))
def test_a_config_error_traceback_prints_no_secret(tmp_path, breakage):
    path = _write(tmp_path, breakage)

    with pytest.raises(Exception) as caught:
        Config.from_yaml(path)

    assert _leaked("".join(traceback.format_exception(caught.value))) == []
