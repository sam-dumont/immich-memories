"""Phase events are appended as rows: no rewrite per event, no full re-read per poll."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import sqlalchemy as sa

from immich_memories.automation.state_store import AutomationStateStore
from immich_memories.db import downgrade, upgrade
from immich_memories.db.tables import automation_attempts, pipeline_runs
from immich_memories.operations.phases import OperationalPhase, PhaseEvent
from immich_memories.tracking.models import RunMetadata
from immich_memories.tracking.run_database import RunDatabase
from immich_memories.tracking.run_database_rows import run_to_row


def _event(count: int) -> PhaseEvent:
    return PhaseEvent(OperationalPhase.RENDER, count, 500, f"Clip {count} rendered", float(count))


def _statements(store, work) -> list[tuple[str, str]]:
    """The statements `work()` ran against the store, with their parameters as text."""
    seen: list[tuple[str, str]] = []

    def record(_conn, _cursor, statement, parameters, _context, _many):
        seen.append((statement, json.dumps(parameters, default=str)))

    sa.event.listen(store.engine, "before_cursor_execute", record)
    try:
        work()
    finally:
        sa.event.remove(store.engine, "before_cursor_execute", record)
    return seen


def test_an_event_late_in_a_long_run_writes_what_the_first_one_wrote(store):
    runs = RunDatabase(store)
    runs.save_run(RunMetadata(run_id="long", created_at=datetime.now(UTC)))
    first = _statements(store, lambda: runs.update_operational_phase("long", _event(0)))
    for count in range(1, 300):
        runs.update_operational_phase("long", _event(count))

    late = _statements(store, lambda: runs.update_operational_phase("long", _event(300)))

    def written(statements):
        return sum(len(params) for _, params in statements)

    assert written(late) < written(first) * 2
    assert not any("phase_events" in statement for statement, _ in late if "UPDATE" in statement)


def test_a_reader_gets_only_the_events_past_the_one_it_saw(store):
    attempts = AutomationStateStore(store)
    attempt = attempts.start_attempt("wake")
    for count in range(3):
        attempts.update_phase(attempt.id, _event(count))
    seen = attempts.phase_events_after(attempt.id)
    assert [event["current"] for _, event in seen] == [0, 1, 2]
    attempts.update_phase(attempt.id, _event(3))

    new = attempts.phase_events_after(attempt.id, seen[-1][0])

    assert [event["current"] for _, event in new] == [3]
    assert attempts.phase_events_after(attempt.id, new[-1][0]) == []


def test_a_summary_list_skips_events_and_every_other_read_has_them(store):
    runs = RunDatabase(store)
    runs.save_run(RunMetadata(run_id="listed", created_at=datetime.now(UTC)))
    runs.update_operational_phase("listed", _event(1))

    assert runs.list_runs(with_events=False)[0].phase_events == []
    assert [e["current"] for e in runs.list_runs()[0].phase_events] == [1]
    assert [e["current"] for e in runs.get_run("listed").phase_events] == [1]


def test_events_written_by_an_older_version_stay_readable_after_the_upgrade(store):
    downgrade(store, "0015_run_app_version")
    old = [_event(count).to_dict() for count in range(3)]
    with store.begin() as connection:
        row = run_to_row(RunMetadata(run_id="old-run", created_at=datetime.now(UTC)))
        connection.execute(sa.insert(pipeline_runs), [row | {"phase_events": old}])
        for attempt_id, events in (("old-attempt", old), ("quiet-attempt", [])):
            connection.execute(
                sa.insert(automation_attempts).values(
                    id=attempt_id,
                    started_at=datetime.now(UTC).replace(tzinfo=None),
                    outcome="failed",
                    reason="daily wake",
                    last_phase="render" if events else None,
                    phase_events=events,
                )
            )

    upgrade(store)

    assert RunDatabase(store).get_run("old-run").phase_events == old
    attempts = AutomationStateStore(store)
    assert attempts.get_attempt("old-attempt").phase_events == old
    assert attempts.get_attempt("quiet-attempt").phase_events == []
    # New events carry on after the old ones.
    RunDatabase(store).update_operational_phase("old-run", _event(9))
    assert [e["current"] for e in RunDatabase(store).get_run("old-run").phase_events] == [
        0,
        1,
        2,
        9,
    ]
    with store.connect() as connection:
        left = connection.execute(sa.select(pipeline_runs.c.phase_events)).scalars().all()
    assert all(not value for value in left)
