"""Preflight against a wrong Immich address: fast, one row, the cause and the fix on screen."""

from __future__ import annotations

import socket
import time

import pytest
from click.testing import CliRunner

from immich_memories.cli import main


def _closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _preflight_unreachable(tmp_path, *extra: str):
    config_path = tmp_path / "c.yaml"
    config_path.write_text(
        f"immich:\n  url: http://127.0.0.1:{_closed_port()}\n  api_key: not-a-real-key\n"
    )
    started = time.monotonic()
    result = CliRunner().invoke(
        main, ["-c", str(config_path), "preflight", *extra], env={"COLUMNS": "1000"}
    )
    return result, time.monotonic() - started


@pytest.mark.feature("preflight.wrong-address-fast")
def test_unreachable_immich_fails_in_seconds_without_retry_lines(tmp_path):
    result, seconds = _preflight_unreachable(tmp_path)

    assert seconds < 10
    assert "retrying" not in result.output
    assert result.output.count("Connection failed") == 1


@pytest.mark.feature("preflight.shows-fixes")
def test_error_rows_show_cause_and_fix_without_verbose(tmp_path):
    result, _ = _preflight_unreachable(tmp_path)

    assert "Details" in result.output
    assert "has not answered yet" in result.output


@pytest.mark.feature("preflight.shows-fixes")
def test_ok_rows_stay_compact_without_verbose(tmp_path):
    from unittest.mock import patch

    from immich_memories.preflight import CheckResult, CheckStatus

    rows = [
        CheckResult("Fine", CheckStatus.OK, "all good", "internal detail"),
        CheckResult("Broken", CheckStatus.ERROR, "it broke", "do this to fix it"),
    ]
    config_path = tmp_path / "c.yaml"
    config_path.write_text("immich:\n  url: http://immich\n  api_key: k\n")

    # WHY: the real checks reach Immich, an LLM and the GPU; the table is the subject.
    with patch("immich_memories.preflight.run_preflight_checks", return_value=rows):
        result = CliRunner().invoke(
            main, ["-c", str(config_path), "preflight"], env={"COLUMNS": "1000"}
        )

    assert "do this to fix it" in result.output
    assert "internal detail" not in result.output
