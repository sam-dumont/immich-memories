"""No test sees the account's own home, config or network unless it sets them up itself."""

from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest
from click.testing import CliRunner

from immich_memories import config_loader
from immich_memories.cli import main
from tests.conftest import (
    _OUTSIDE_CONNECTIONS,
    _REAL_CONFIG_READS,
    _TEST_ROOT,
    OutsideConnectionRefused,
    _account_home,
    _product_settings,
    _selects_the_real_world,
)


def test_a_cli_run_without_a_home_reads_the_suites_config_not_the_accounts():
    config_file = Path.home() / ".immich-memories" / "config.yaml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text("immich:\n  url: http://127.0.0.1:9/suite-home\n")

    result = CliRunner().invoke(main, ["config", "show", "immich.url"])

    assert result.exit_code == 0, result.output
    assert "suite-home" in result.output
    assert _TEST_ROOT is not None
    assert Path.home().resolve().is_relative_to(_TEST_ROOT.resolve())
    assert Path.home().resolve() != _account_home()


def test_the_shells_provider_and_immich_settings_do_not_reach_a_test():
    leaked = [
        key
        for key in ("IMMICH_URL", "IMMICH_API_KEY", "OPENAI_API_KEY", "ZAI_API_KEY")
        if key in os.environ
    ]

    assert leaked == []


def test_loading_the_accounts_own_config_fails_the_test_even_when_caught():
    path = _account_home() / ".immich-memories" / "config.yaml"

    with pytest.raises(RuntimeError, match="developer's own config"):
        config_loader.load_config(path)

    assert [str(path.resolve())] == _REAL_CONFIG_READS
    # Expected here: clear it so the autouse check does not fail this test.
    _REAL_CONFIG_READS.clear()


def test_a_connection_outside_this_machine_is_refused():
    with pytest.raises(OutsideConnectionRefused):
        socket.create_connection(("192.0.2.1", 80), timeout=1)

    assert _OUTSIDE_CONNECTIONS == ["('192.0.2.1', 80)"]
    _OUTSIDE_CONNECTIONS.clear()


def test_a_connection_to_this_machine_goes_through():
    with socket.create_server(("127.0.0.1", 0)) as server:
        port = server.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            pass

    assert _OUTSIDE_CONNECTIONS == []


def test_only_a_run_that_can_select_real_world_tests_keeps_the_real_environment():
    assert not _selects_the_real_world("not integration and not e2e and not container")
    assert not _selects_the_real_world("e2e")
    assert _selects_the_real_world("integration")
    assert _selects_the_real_world("container")
    assert _selects_the_real_world("")


def test_the_scrub_drops_product_settings_and_keeps_the_suites_own():
    shell = [
        "IMMICH_URL",
        "OPENAI_API_KEY",
        "IMMICH_MEMORIES_LLM__MODEL",
        "IMMICH_MEMORIES_AUTH_PASSWORD",
        "IMMICH_MEMORIES_TEST_DATABASE_URL",
        "IMMICH_MEMORIES_E2E_DATABASE_URL",
        "IMMICH_MEMORIES_CONTAINER_IMAGE",
        "IMMICH_MEMORIES_PRIVATE_TERMS",
        "IMMICH_MEMORIES_DATABASE_URL",
        "PATH",
    ]

    assert sorted(_product_settings(shell)) == [
        "IMMICH_MEMORIES_AUTH_PASSWORD",
        "IMMICH_MEMORIES_LLM__MODEL",
        "IMMICH_URL",
        "OPENAI_API_KEY",
    ]
