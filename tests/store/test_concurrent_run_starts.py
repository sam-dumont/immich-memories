"""Runs started at one instant from the web client, the CLI, the daily timer and the trigger.

Six processes share one store and wait on one barrier (tests/store/concurrent_starts.py): two
web cuts, a CLI `generate`, the timer firing, a trigger and a sweeper. While every run is
alive the test reads the store: each run has its own id and its own liveness lease, the
automation lease let exactly one automatic film through, and no sweep ended a live run. Then
the runs finish, and each one ends with its own record, terminal.
"""

from __future__ import annotations

import multiprocessing
import secrets
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from queue import Empty
from typing import Any

import pytest
import sqlalchemy as sa

from immich_memories.automation.models import ALREADY_RUNNING, AutoOutcome
from immich_memories.automation.state_store import AutomationStateStore
from immich_memories.db import StoreLocation, open_store
from immich_memories.db.tables.operations import automation_attempts
from immich_memories.tracking.models import RunMetadata
from immich_memories.tracking.orphaned_runs import interrupt_orphaned_runs
from immich_memories.tracking.run_database import RunDatabase
from tests.features.automation_library import write_config
from tests.store.concurrent_starts import (
    AUTOMATIC_ROLES,
    MANUAL_ROLES,
    PATIENCE_SECONDS,
    SWEEPER,
    run_role,
)

ROLES = (*MANUAL_ROLES, *AUTOMATIC_ROLES, SWEEPER)
# A run its process left behind: the sweeps must end this one, and only this one.
DEAD = "20260301_090000_dead"


class Round:
    """One round: the processes, what they reported, and the store they share."""

    def __init__(self, config: Path, store: Any) -> None:
        context = multiprocessing.get_context("spawn")
        self.store = store
        self.start = context.Barrier(len(ROLES) + 1)
        self.release = context.Event()
        self.events = context.Queue()
        self.reported: list[tuple[Any, ...]] = []
        self.processes = [
            context.Process(
                target=run_role,
                args=(role, config, self.start, self.release, self.events),
                name=role,
                daemon=True,
            )
            for role in ROLES
        ]

    def __enter__(self) -> Round:
        for process in self.processes:
            process.start()
        self.start.wait(PATIENCE_SECONDS)
        return self

    def __exit__(self, *exc: object) -> None:
        self.release.set()
        for process in self.processes:
            process.join(PATIENCE_SECONDS)
            if process.is_alive():
                process.kill()

    def of(self, kind: str) -> list[tuple[Any, ...]]:
        return [event for event in self.reported if event[0] == kind]

    def wait_for(self, done: Any) -> None:
        """Read reports until `done(self)` holds; a worker's traceback fails the test."""
        deadline = time.monotonic() + PATIENCE_SECONDS
        while not done(self):
            assert time.monotonic() < deadline, f"workers stalled: {self.reported}"
            try:
                event = self.events.get(timeout=0.5)
            except Empty:
                dead = [p.name for p in self.processes if p.exitcode not in (None, 0)]
                assert not dead, f"{dead} exited early: {self.reported}"
                continue
            assert event[0] != "error", f"{event[1]} failed:\n{event[2]}"
            self.reported.append(event)

    def live_runs(self) -> dict[str, str]:
        """role -> run id, for every run a worker reported open."""
        return {event[1]: event[2] for event in self.of("run")}


def _answered(round_: Round, role: str) -> tuple[Any, ...] | None:
    return next((event[2:] for event in round_.of("auto") if event[1] == role), None)


def _all_started(round_: Round) -> bool:
    """Three manual runs and one automatic run open, and the automatic entries settled.

    A timer that won answers only once its film is done, so its child's run stands for it.
    """
    timer_settled = _answered(round_, "timer") is not None or "timer-child" in round_.live_runs()
    return len(round_.of("run")) >= 4 and _answered(round_, "trigger") is not None and timer_settled


def _all_ended(round_: Round) -> bool:
    ended = {event[1] for event in round_.of("done")}
    trigger = _answered(round_, "trigger")
    return (
        ended >= set(MANUAL_ROLES)
        and bool(round_.of("swept"))
        and _answered(round_, "timer") is not None
        and (trigger is None or not trigger[0] or "trigger" in ended)
    )


def _one_automatic_film(round_: Round) -> str:
    """Which automatic entry made the film; the other must have been turned away."""
    timer_fired, timer_outcome, timer_reason = _answered(round_, "timer") or ()
    accepted, status, _detail = _answered(round_, "trigger") or ()
    children = [role for role in round_.live_runs() if role.endswith("-child")]
    if accepted:
        assert children == ["trigger-child"], round_.reported
        # The timer found the lease taken, or today's attempt already running, and waits.
        assert (timer_fired, timer_outcome, timer_reason) in (
            (True, "skipped", ALREADY_RUNNING),
            (False, "running", "http trigger"),
        ), round_.reported
        assert ("done", "trigger", "completed") in round_.reported
        return "trigger"
    assert status == 409, round_.reported
    assert children == ["timer-child"], round_.reported
    assert (timer_fired, timer_outcome) == (True, "completed"), round_.reported
    return "timer"


def _run_leases(store: Any, location: StoreLocation) -> list[str]:
    """The run ids whose liveness lease is held: one lock file, or one advisory lock, each."""
    if location.sqlite_path is not None:
        return sorted(p.stem for p in (location.sqlite_path.parent / "run-leases").glob("*.lock"))
    # The dead run is left out: a sweep's probe holds its lease for an instant.
    run_ids = [run.run_id for run in RunDatabase(store).list_runs(limit=50) if run.run_id != DEAD]
    keys = {run_id: f"{location.schema}:run:{run_id}" for run_id in run_ids}
    with store.connect() as connection:
        held = connection.execute(
            sa.text(
                "SELECT objid::bigint FROM pg_locks WHERE locktype = 'advisory' AND granted"
                " AND classid = 8710002 AND objsubid = 2"
            )
        ).scalars()
        holders = list(held)
        hashes = {
            run_id: connection.execute(
                sa.text("SELECT hashtext(:key)::bigint & 4294967295"), {"key": key}
            ).scalar()
            for run_id, key in keys.items()
        }
    return sorted(run_id for run_id, h in hashes.items() for holder in holders if holder == h)


def _plant_dead_run(store: Any) -> None:
    RunDatabase(store).save_run(
        RunMetadata(run_id=DEAD, created_at=datetime.now(tz=UTC), status="running")
    )


@pytest.fixture
def shared_config(location: StoreLocation, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """One install every process reads: its store is this test's store on this backend."""
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_URL", location.url)
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_SCHEMA", location.schema)
    # The sealed session's output folder outranks the file; the stand-in films stay in this test.
    monkeypatch.setenv("IMMICH_MEMORIES_OUTPUT__DIRECTORY", str(tmp_path / "install" / "films"))
    return write_config(
        tmp_path / "install",
        automation={"enabled": True, "daily_at": "00:00"},
        server={"trigger_token": secrets.token_hex(32)},
    )


def test_runs_started_at_once_from_every_entry_point_keep_their_own_records(
    shared_config: Path, location: StoreLocation
) -> None:
    store = open_store(location=location)
    database = RunDatabase(store)
    _plant_dead_run(store)

    with Round(shared_config, store) as round_:
        round_.wait_for(_all_started)
        live = round_.live_runs()

        # Every run alive at once: its own id, its own lease, untouched by every sweep.
        assert len(set(live.values())) == len(live) == 4, live
        assert set(interrupt_orphaned_runs(store)) <= {DEAD}
        statuses = {role: database.get_run(run_id) for role, run_id in live.items()}
        assert {role: run.status for role, run in statuses.items() if run} == dict.fromkeys(
            live, "running"
        )
        assert all(database.run_lease(run_id).held_elsewhere() for run_id in live.values())
        assert _run_leases(store, location) == sorted(live.values())
        attempts = AutomationStateStore(store)
        running = attempts.get_last_attempt()
        assert running is not None and running.outcome is AutoOutcome.RUNNING

        round_.release.set()
        round_.wait_for(_all_ended)

    maker = _one_automatic_film(round_)
    assert round_.live_runs() == live, round_.reported
    for process in round_.processes:
        assert process.exitcode == 0, (process.name, process.exitcode, round_.reported)
    [(_, _, swept, sweeps)] = round_.of("swept")
    assert set(swept) <= {DEAD} and sweeps > 0, (swept, sweeps)

    # Each run ends terminal, as the record its own process wrote; the dead one interrupted.
    runs = {run.run_id: run for run in database.list_runs(limit=50)}
    assert set(runs) == {*live.values(), DEAD}
    assert runs[DEAD].status == "interrupted"
    for role, memory_type in MANUAL_ROLES.items():
        run = runs[live[role]]
        assert (run.status, run.source, run.memory_type) == ("completed", "manual", memory_type)
    film = runs[live[f"{maker}-child"]]
    assert (film.status, film.source) == ("completed", "auto")
    assert film.automation_attempt_id == running.id
    assert database.run_lease(film.run_id).held_elsewhere() is False
    ended = attempts.get_attempt(running.id)
    assert ended is not None and ended.outcome is AutoOutcome.COMPLETED, ended
    assert ended.run_id == film.run_id
    with store.connect() as connection:
        every_attempt = connection.execute(sa.select(automation_attempts.c.id)).scalars().all()
    assert every_attempt == [running.id]


def test_a_trigger_during_the_timers_housekeeping_still_starts(
    shared_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every 30 seconds the timer settles attempts a dead process left running.

    It took the automation lease to look, even with nothing to settle, so a trigger landing in
    that moment was answered 409 "a run is already active" and made no film.
    """
    from immich_memories.automation import runner
    from immich_memories.config.loader import Config

    config = Config.from_yaml(shared_config)
    looking, answered = threading.Event(), threading.Event()
    settle = runner.end_interrupted_attempts

    def slow_settle(*args: Any) -> Any:
        if threading.current_thread().name == "timer":
            looking.set()
            answered.wait(PATIENCE_SECONDS)
        return settle(*args)

    # WHY: holds the timer inside its housekeeping while the trigger arrives.
    monkeypatch.setattr(runner, "end_interrupted_attempts", slow_settle)
    timer = threading.Thread(
        target=runner.AutoRunner(config).settle_interrupted_attempts, name="timer"
    )
    timer.start()
    while timer.is_alive() and not looking.is_set():
        time.sleep(0.01)
    try:
        started = runner.AutoRunner(config).start_one(reason="http trigger")
    finally:
        answered.set()
        timer.join(PATIENCE_SECONDS)
    started.lease.release()

    assert started.attempt.outcome is AutoOutcome.RUNNING
    assert started.attempt.reason == "http trigger"
