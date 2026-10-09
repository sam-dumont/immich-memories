"""Storage failures reach the terminal without private paths or a masked root cause."""

import errno
import sqlite3
from unittest.mock import create_autospec

import pytest
import sqlalchemy as sa
from click.testing import CliRunner

from immich_memories.api.immich import SyncImmichClient
from immich_memories.cli import main
from immich_memories.db import open_store
from immich_memories.tracking.run_observations import observe_run


@pytest.mark.parametrize("code", [errno.ENOSPC, errno.EDQUOT])
def test_generate_reports_storage_recovery_without_printing_the_failed_path(
    tmp_path, monkeypatch, code
):
    path = tmp_path / "config.yaml"
    path.write_text("immich:\n  url: http://immich.test\n  api_key: test-key\n")
    client = create_autospec(SyncImmichClient, instance=True)
    client.require_read_permissions.side_effect = OSError(
        code, "write failed", "/private/configured-volume/progress.json"
    )
    # WHY: the client boundary fails without contacting a real library or probing hardware.
    monkeypatch.setattr("immich_memories.api.immich.SyncImmichClient", lambda **_kw: client)
    result = CliRunner().invoke(main, ["-c", str(path), "generate", "--year=2024", "--no-render"])

    assert result.exit_code != 0
    assert "Storage is full" in result.output
    assert "Expand" in result.output
    assert "Do not delete the store" in result.output
    assert "configured-volume" not in result.output


def _full_database(*_args):
    error = sqlite3.OperationalError("database or disk is full")
    error.sqlite_errorcode = sqlite3.SQLITE_FULL
    raise error


def test_cli_reports_a_full_store_without_a_traceback():
    store = open_store()
    # WHY: fail actual database access without filling the developer's filesystem.
    sa.event.listen(store.engine, "before_cursor_execute", _full_database)
    try:
        result = CliRunner().invoke(main, ["report", "--json"])
    finally:
        sa.event.remove(store.engine, "before_cursor_execute", _full_database)
    assert result.exit_code != 0
    assert "Storage is full" in result.output
    assert "Traceback" not in result.output


def test_database_cleanup_failure_does_not_replace_the_original_failure(caplog):
    store = open_store()
    try:
        with (
            pytest.raises(RuntimeError, match="caption service stopped"),
            observe_run(store, source="prepare", capture_system=False),
        ):
            # WHY: the database fills after the run starts, before failure bookkeeping.
            sa.event.listen(store.engine, "before_cursor_execute", _full_database)
            raise RuntimeError("caption service stopped")
    finally:
        sa.event.remove(store.engine, "before_cursor_execute", _full_database)
    assert "Could not save" in caplog.text
