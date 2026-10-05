"""Which `running` runs still have a live owner, and settling the ones that do not.

Every run holds its own lease from the moment its row is written until it ends: a lock file
beside a SQLite store, an advisory lock on PostgreSQL. The operating system or the server drops
it when the owning process dies, so a `running` row whose lease is free belongs to nobody. The
CLI and the web server both read liveness this way, so they agree on what is still running.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from immich_memories.db import Store
from immich_memories.tracking.run_database import RunDatabase

logger = logging.getLogger(__name__)


def interrupt_orphaned_runs(store: Store) -> list[str]:
    """Mark every `running` run whose owner is gone `interrupted`; return their ids."""
    database = RunDatabase(store)
    dead = [
        run_id
        for run_id in database.running_run_ids()
        if not database.run_lease(run_id).held_elsewhere()
    ]
    return database.interrupt_runs(dead, datetime.now(tz=UTC))


def settle_orphaned_runs(store: Store) -> None:
    """Interrupt dead runs before a run list is read, logging each; never fails the read."""
    try:
        for run_id in interrupt_orphaned_runs(store):
            logger.warning(
                "Run %s was left running by a stopped process; marked interrupted", run_id
            )
    except Exception:  # WHY: a store hiccup must not keep the history from being read
        logger.exception("Could not settle runs left running")
