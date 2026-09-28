"""Leases hold across processes: lock files on SQLite, advisory locks on a shared PostgreSQL."""

from __future__ import annotations

import multiprocessing
import os
import signal
import time
import uuid
from pathlib import Path

import pytest

from immich_memories.db import StoreLocation, close_stores, open_store
from immich_memories.db.leases import Lease, LeaseHeldError

from .backends import drop_schema, pg_url, requires_postgres


def _hold(url: str, schema: str, lock_path: str, ready, release) -> None:
    """A second process: take the lease, say so, hold it until told to let go."""
    store = open_store(location=StoreLocation(url=url, schema=schema))
    lease = Lease("automation", Path(lock_path), store)
    lease.acquire()
    ready.set()
    release.wait(timeout=60)
    lease.release()


def _holder(location: StoreLocation, lock_path: Path):
    context = multiprocessing.get_context("spawn")
    ready, release = context.Event(), context.Event()
    process = context.Process(
        target=_hold, args=(location.url, location.schema, str(lock_path), ready, release)
    )
    process.start()
    assert ready.wait(timeout=60), "the holder never took the lease"
    return process, release


def _acquire_eventually(lease: Lease, seconds: float = 10.0) -> None:
    deadline = time.monotonic() + seconds
    while True:
        try:
            lease.acquire()
            return
        except LeaseHeldError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.1)


def test_a_second_process_waits_its_turn(store, tmp_path):
    lock_path = tmp_path / ".auto.lock"
    process, release = _holder(store.location, lock_path)
    lease = Lease("automation", lock_path, store)
    try:
        with pytest.raises(LeaseHeldError):
            lease.acquire()
        assert lease.held_elsewhere()
    finally:
        release.set()
        process.join(timeout=30)

    lease.acquire()
    lease.release()


def test_a_killed_holder_frees_the_lease(store, tmp_path):
    lock_path = tmp_path / ".auto.lock"
    process, _ = _holder(store.location, lock_path)
    lease = Lease("automation", lock_path, store)
    with pytest.raises(LeaseHeldError):
        lease.acquire()

    assert process.pid is not None
    os.kill(process.pid, signal.SIGKILL)
    process.join(timeout=30)

    _acquire_eventually(lease)
    lease.release()


def test_one_lease_per_name(store, tmp_path):
    first = Lease("pipeline", tmp_path / ".lock", store)
    other_name = Lease("automation", tmp_path / ".auto.lock", store)
    with first, other_name, pytest.raises(LeaseHeldError):
        Lease("pipeline", tmp_path / ".lock", store).acquire()
    with Lease("pipeline", tmp_path / ".lock", store):
        pass


@requires_postgres
def test_two_schemas_in_one_database_do_not_block_each_other(tmp_path):
    url, schemas = pg_url(), [f"test_{uuid.uuid4().hex[:12]}" for _ in range(2)]
    try:
        stores = [open_store(location=StoreLocation(url=url, schema=s)) for s in schemas]
        with (
            Lease("automation", tmp_path / "a", stores[0]),
            Lease("automation", tmp_path / "b", stores[1]),
            pytest.raises(LeaseHeldError),
        ):
            Lease("automation", tmp_path / "c", stores[0]).acquire()
    finally:
        close_stores()
        for schema in schemas:
            drop_schema(url, schema)


def test_a_film_attempt_is_live_while_held_and_interrupted_after(store, tmp_path):
    from immich_memories.operations.editorial_attempt import (
        EditorialAttempt,
        read_editorial_attempt,
    )

    with EditorialAttempt(tmp_path, request={}, store=store) as attempt:
        assert read_editorial_attempt(attempt.directory, store)["status"] == "running"
        record = (attempt.directory / "status.private.json").read_text()

    # A holder that died mid-run left "running" behind; nobody holds its lease any more.
    (attempt.directory / "status.private.json").write_text(record)
    assert read_editorial_attempt(attempt.directory, store)["status"] == "interrupted"
