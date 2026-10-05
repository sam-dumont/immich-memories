"""A config that names a reader but leaves `llm.enabled` unset says so loudly.

#1833 defaulted `llm.enabled` to false. A 0.103.0 config with `base_url`/`model`
set and no `enabled` field upgrades straight into a reader that is off, with
model titles, music mood and model selection all gone silently. The only
previous signals were an INFO "Tier auto resolved" line and a preflight check
that only runs when asked for. This warns at every config load instead (#2094).
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from immich_memories.config_loader import Config


def _write(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def test_a_configured_reader_left_disabled_warns_once(tmp_path: Path, caplog) -> None:
    path = _write(tmp_path, {"advanced": {"llm": {"base_url": "http://llm:8080/v1", "model": "m"}}})

    with caplog.at_level(logging.WARNING):
        config = Config.from_yaml(path)

    assert config.llm.enabled is False
    warnings = [r for r in caplog.records if "advanced.llm.enabled" in r.getMessage()]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "model" in message
    assert "base_url" in message
    assert "enabled: true" in message


def test_an_enabled_reader_warns_about_nothing(tmp_path: Path, caplog) -> None:
    path = _write(
        tmp_path,
        {"advanced": {"llm": {"base_url": "http://llm:8080/v1", "model": "m", "enabled": True}}},
    )

    with caplog.at_level(logging.WARNING):
        config = Config.from_yaml(path)

    assert config.llm.enabled is True
    assert not [r for r in caplog.records if "advanced.llm.enabled" in r.getMessage()]


def test_no_reader_configured_warns_about_nothing(tmp_path: Path, caplog) -> None:
    path = _write(tmp_path, {"photos": {"duration": 4.0}})

    with caplog.at_level(logging.WARNING):
        config = Config.from_yaml(path)

    assert config.llm.enabled is False
    assert not [r for r in caplog.records if "advanced.llm.enabled" in r.getMessage()]


def test_the_warning_never_prints_the_api_key_value(tmp_path: Path, caplog) -> None:
    path = _write(
        tmp_path,
        {"advanced": {"llm": {"base_url": "http://llm:8080/v1", "api_key": "sk-secret-value"}}},
    )

    with caplog.at_level(logging.WARNING):
        Config.from_yaml(path)

    message = "\n".join(r.getMessage() for r in caplog.records)
    assert "sk-secret-value" not in message
    assert "api_key" in message
