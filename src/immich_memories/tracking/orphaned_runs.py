"""Runs a dead process left `running`: marked interrupted when nothing holds the pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from immich_memories.db import Store
from immich_memories.db.leases import Lease
from immich_memories.tracking.run_database import RunDatabase


def interrupt_orphaned_runs(store: Store, lock_path: Path) -> list[str]:
    """Mark every `running` run `interrupted` unless a pipeline is alive; return their ids.

    Generation runs under the one `pipeline` lease, which the operating system or the server
    drops when its holder dies, so a `running` row with the lease free belongs to no live job.
    """
    pipeline = Lease("pipeline", lock_path, store)
    if lock_path.exists() and pipeline.held_elsewhere():
        return []
    return RunDatabase(store).interrupt_running_runs(datetime.now(tz=UTC))
