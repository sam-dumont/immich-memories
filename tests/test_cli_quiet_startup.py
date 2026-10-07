"""The CLI group quiets request logging and skips the tier probe for --help (#2194)."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner

from immich_memories.cli import main
from immich_memories.config_loader import set_config
from immich_memories.db import close_stores


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch) -> Iterator[None]:
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_URL", f"sqlite:///{tmp_path / 'store.db'}")
    monkeypatch.setenv("IMMICH_MEMORIES_TIER", "auto")
    yield
    set_config(None)
    close_stores()
    logging.getLogger("httpx").setLevel(logging.NOTSET)
    logging.getLogger("httpcore").setLevel(logging.NOTSET)


@pytest.fixture
def chatty(monkeypatch) -> str:
    @click.command("chatty-probe")
    def chatty_probe() -> None:
        logging.getLogger("httpx").info("HTTP Request: GET http://x/api/y")

    monkeypatch.setitem(main.commands, "chatty-probe", chatty_probe)
    return "chatty-probe"


def test_no_request_line_without_verbose(isolated, chatty):
    result = CliRunner().invoke(main, [chatty])

    assert result.exit_code == 0
    assert "HTTP Request" not in result.output


def test_verbose_still_shows_request_lines(isolated, chatty):
    result = CliRunner().invoke(main, ["-v", chatty])

    assert "HTTP Request" in result.output


def test_help_contacts_nothing(isolated):
    # WHY: the tier probe is the one network call a config load can make.
    with patch("immich_memories.config_tiers.inference_acceleration") as probe:
        result = CliRunner().invoke(main, ["runs", "--help"])

    assert result.exit_code == 0
    probe.assert_not_called()
