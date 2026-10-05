"""Unit-tier coverage for the PostgreSQL branch of `db/backup.py`'s restore.

The real server is the only way to prove `pg_restore` itself behaves (see
`tests/store/test_backup_restore.py`, run via `make test-store`), but that suite never runs
in the plain unit tier, so the rename-aside / restore-fresh / roll-back control flow around
it would otherwise go uncovered on every PR. These tests fake the two external boundaries
`_restore_postgresql` touches — the PostgreSQL connection and the `pg_restore` subprocess —
and drive that control flow directly, through `_restore_postgresql` itself (the function
`restore_store` dispatches to for this backend).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
import sqlalchemy as sa

from immich_memories.db import backup as backup_module
from immich_memories.db.backup import BackupError, Manifest
from immich_memories.db.bootstrap import StoreLocation


class _FakeConnection:
    """Stands in for a real `psycopg` connection: records DDL and answers schema questions
    from an in-memory set of names, instead of asking a live PostgreSQL server."""

    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state
        self.dialect = _FakeDialect()

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def has_schema(self, name: str) -> bool:
        return name in self.state["schemas"]

    def execute(self, clause: Any) -> Any:
        self.state["calls"].append(clause)
        if isinstance(clause, sa.sql.elements.TextClause):
            return self._execute_text(str(clause))
        if isinstance(clause, sa.schema.DropSchema):
            self.state["schemas"].discard(clause.element)
            return None
        raise AssertionError(f"unexpected clause: {clause!r}")

    def _execute_text(self, text: str) -> Any:
        if "has_database_privilege" in text:
            return _Scalar(self.state["can_create"])
        if text.startswith("ALTER SCHEMA"):
            old, new = text.removeprefix("ALTER SCHEMA ").split(" RENAME TO ")
            self.state["schemas"].discard(old)
            self.state["schemas"].add(new)
            return None
        raise AssertionError(f"unexpected statement: {text}")


class _Scalar:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar(self) -> Any:
        return self._value


class _FakePreparer:
    def quote_schema(self, name: str) -> str:
        return name


class _FakeDialect:
    identifier_preparer = _FakePreparer()


class _FakeEngine:
    """Stands in for `sa.create_engine(location.sa_url)`, the only place
    `_restore_postgresql` opens a connection to the server."""

    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state
        self.disposed = False

    @contextmanager
    def begin(self) -> Iterator[_FakeConnection]:
        yield _FakeConnection(self.state)

    def dispose(self) -> None:
        self.disposed = True


def _state(*, schemas: set[str], can_create: bool = True) -> dict[str, Any]:
    return {"schemas": set(schemas), "can_create": can_create, "calls": []}


@pytest.fixture
def location() -> StoreLocation:
    return StoreLocation(url="postgresql+psycopg://user@host/db", schema="store")


@pytest.fixture
def manifest() -> Manifest:
    return Manifest(
        app_version="0",
        revisions=["head"],
        backend="postgresql",
        schema="store",
        counts={"people": 3},
        created_at="2026-01-01T00:00:00+00:00",
    )


def _patch_connection(monkeypatch: pytest.MonkeyPatch, state: dict[str, Any]) -> None:
    # WHY: `sa.create_engine`/`sa.inspect` are the only way `_restore_postgresql` and its
    # helpers reach a real PostgreSQL connection; faking them drives the rename/restore/
    # rollback control flow against an in-memory set of schema names instead of a live
    # server, whose actual `pg_restore` behaviour is covered separately by `make test-store`.
    monkeypatch.setattr(backup_module.sa, "create_engine", lambda *_a, **_k: _FakeEngine(state))
    monkeypatch.setattr(backup_module.sa, "inspect", lambda connection: connection)
    # WHY: resolving the pg_restore binary on PATH is an environment detail unrelated to the
    # control flow under test; `_run` (the subprocess call itself) is faked per test below.
    monkeypatch.setattr(backup_module, "_tool", lambda name: name)


def _patch_run(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[list[str]],
    *,
    state: dict[str, Any] | None = None,
    creates_schema: str | None = None,
    error: str | None = None,
) -> None:
    # WHY: the actual `pg_restore` subprocess is what `make test-store` proves against a real
    # server; here only the fact that `_restore_postgresql` invoked it, and the one side
    # effect the surrounding logic depends on (the schema it creates), matter for the
    # rename/rollback control flow.
    def fake_run(
        command: list[str], _location: StoreLocation, tolerated: str | None = None
    ) -> None:
        calls.append(command)
        if error is not None:
            raise BackupError(error)
        if state is not None and creates_schema is not None:
            state["schemas"].add(creates_schema)

    monkeypatch.setattr(backup_module, "_run", fake_run)


def test_restore_renames_the_live_schema_aside_then_restores_fresh_and_drops_it(
    monkeypatch, location, manifest, tmp_path
) -> None:
    state = _state(schemas={"store"})
    _patch_connection(monkeypatch, state)
    run_calls: list[list[str]] = []
    _patch_run(monkeypatch, run_calls, state=state, creates_schema="store")
    monkeypatch.setattr(backup_module, "_verify_restore", lambda *_a, **_k: None)

    backup_module._restore_postgresql(location, tmp_path / "store.dump", manifest)

    assert run_calls, "pg_restore should have been invoked"
    assert state["schemas"] == {"store"}
    assert "store__before_restore" not in state["schemas"]


def test_restore_into_a_target_with_no_existing_schema_skips_the_aside_dance(
    monkeypatch, location, manifest, tmp_path
) -> None:
    state = _state(schemas=set())
    _patch_connection(monkeypatch, state)
    _patch_run(monkeypatch, [], state=state, creates_schema="store")
    monkeypatch.setattr(backup_module, "_verify_restore", lambda *_a, **_k: None)

    backup_module._restore_postgresql(location, tmp_path / "store.dump", manifest)

    assert state["schemas"] == {"store"}
    assert not any(isinstance(call, sa.schema.DropSchema) for call in state["calls"])


def test_restore_under_a_different_backup_schema_name_renames_into_place(
    monkeypatch, location, tmp_path
) -> None:
    manifest = Manifest(
        app_version="0",
        revisions=["head"],
        backend="postgresql",
        schema="other_schema",
        counts={"people": 3},
        created_at="2026-01-01T00:00:00+00:00",
    )
    state = _state(schemas={"store"})
    _patch_connection(monkeypatch, state)
    _patch_run(monkeypatch, [], state=state, creates_schema="other_schema")
    monkeypatch.setattr(backup_module, "_verify_restore", lambda *_a, **_k: None)

    backup_module._restore_postgresql(location, tmp_path / "store.dump", manifest)

    assert state["schemas"] == {"store"}


def test_a_row_count_mismatch_after_a_good_pg_restore_renames_the_schema_back(
    monkeypatch, location, manifest, tmp_path
) -> None:
    state = _state(schemas={"store"})
    _patch_connection(monkeypatch, state)
    _patch_run(monkeypatch, [], state=state, creates_schema="store")

    def failing_verify(*_a: object, **_k: object) -> None:
        raise BackupError(
            "the restored store does not match its manifest: people: 3 expected, 0 found"
        )

    monkeypatch.setattr(backup_module, "_verify_restore", failing_verify)
    monkeypatch.setattr(backup_module, "close_stores", lambda: None)

    with pytest.raises(BackupError, match="does not match its manifest"):
        backup_module._restore_postgresql(location, tmp_path / "store.dump", manifest)

    assert state["schemas"] == {"store"}
    assert "store__before_restore" not in state["schemas"]


def test_a_failing_pg_restore_leaves_the_live_schema_exactly_as_it_was(
    monkeypatch, location, manifest, tmp_path
) -> None:
    state = _state(schemas={"store"})
    _patch_connection(monkeypatch, state)
    _patch_run(monkeypatch, [], error="pg_restore failed: corrupt archive")
    verify_calls: list[object] = []
    monkeypatch.setattr(backup_module, "_verify_restore", lambda *a, **_k: verify_calls.append(a))
    monkeypatch.setattr(backup_module, "close_stores", lambda: None)

    with pytest.raises(BackupError, match="corrupt archive"):
        backup_module._restore_postgresql(location, tmp_path / "store.dump", manifest)

    assert not verify_calls, "a failed pg_restore must never reach the manifest check"
    assert state["schemas"] == {"store"}


def test_a_leftover_aside_schema_refuses_the_restore_without_touching_anything(
    monkeypatch, location, manifest, tmp_path
) -> None:
    state = _state(schemas={"store", "store__before_restore"})
    _patch_connection(monkeypatch, state)
    _patch_run(monkeypatch, [])

    with pytest.raises(BackupError, match="leftover schema"):
        backup_module._restore_postgresql(location, tmp_path / "store.dump", manifest)

    assert state["schemas"] == {"store", "store__before_restore"}


def test_missing_create_privilege_refuses_the_restore_before_any_rename(
    monkeypatch, location, manifest, tmp_path
) -> None:
    state = _state(schemas={"store"}, can_create=False)
    _patch_connection(monkeypatch, state)
    _patch_run(monkeypatch, [])

    with pytest.raises(BackupError, match="CREATE on database"):
        backup_module._restore_postgresql(location, tmp_path / "store.dump", manifest)

    assert state["schemas"] == {"store"}


def test_a_backup_schema_name_already_in_use_elsewhere_refuses_the_restore(
    monkeypatch, location, tmp_path
) -> None:
    """The backup was taken from a schema named `other_schema`, and this database already
    has one by that name (unrelated to the live `store` schema being restored into)."""
    manifest = Manifest(
        app_version="0",
        revisions=["head"],
        backend="postgresql",
        schema="other_schema",
        counts={"people": 3},
        created_at="2026-01-01T00:00:00+00:00",
    )
    state = _state(schemas={"store", "other_schema"})
    _patch_connection(monkeypatch, state)
    _patch_run(monkeypatch, [])

    with pytest.raises(BackupError, match="needs it free"):
        backup_module._restore_postgresql(location, tmp_path / "store.dump", manifest)

    assert state["schemas"] == {"store", "other_schema"}
