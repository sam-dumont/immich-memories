"""Stdout carries only a command's output; every log line goes to stderr (#1570).

A `--json` command's stdout must parse as one JSON document even with INFO logging on:
the CLI's log handler wrote to stdout, so a config or migration log line landed ahead of
the JSON and the document no longer parsed.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from immich_memories.cli import main
from immich_memories.config_loader import Config
from immich_memories.logging_config import configure_logging

JSON_COMMANDS = [
    ["runs", "storage", "--json"],
    ["report", "--json"],
    ["auto", "status", "--json"],
    ["auto", "suggest", "--json"],
]


def _config(tmp_path: Path) -> Config:
    return Config(
        output={"directory": str(tmp_path / "outputs")},
        cache={"directory": str(tmp_path / "cache"), "database": str(tmp_path / "state.db")},
    )


@pytest.mark.parametrize("args", JSON_COMMANDS, ids=lambda args: " ".join(args))
def test_a_json_command_prints_one_document_and_logs_to_stderr(tmp_path, monkeypatch, args):
    from immich_memories.tracking import RunTracker

    config = _config(tmp_path)
    tracker = RunTracker(capture_system=False)
    tracker.start_run()
    tracker.fail_run("fixture")

    def noisy_config(*_args, **_kwargs):
        logging.getLogger("immich_memories.config").info("startup diagnostic")
        logging.getLogger("alembic.runtime.migration").info("Context impl SQLiteImpl.")
        return config

    def quiet_suggest(self, *_args, **_kwargs):
        logging.getLogger("immich_memories.automation").info("scanning the library")
        return []

    # WHY: the config boundary stands in for a real config file that logs as it loads.
    monkeypatch.setattr("immich_memories.cli.get_config", noisy_config)
    monkeypatch.setattr("immich_memories.config.get_config", noisy_config)
    # WHY: `auto suggest` would scan a live Immich library.
    monkeypatch.setattr("immich_memories.automation.runner.AutoRunner.suggest", quiet_suggest)
    monkeypatch.setenv("IMMICH_MEMORIES_LOG_LEVEL", "INFO")
    with patch("immich_memories.cli.init_config_dir"):
        result = CliRunner().invoke(main, args)

    assert result.exit_code == 0, result.output
    json.loads(result.stdout)
    assert "startup diagnostic" in result.stderr


def test_the_log_handler_writes_to_stderr(capsys):
    configure_logging(level="INFO")
    logging.getLogger("immich_memories.test").info("a log line")

    captured = capsys.readouterr()
    assert "a log line" not in captured.out
    assert "a log line" in captured.err
