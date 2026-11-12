"""Re-label the films delivered to Immich from their stored runs (#2627).

The CLI and the web route both come here: a run's label is rebuilt from its record by
`label_for_run`, exactly as an upload builds it, and written to the asset the run was delivered
as. The waits are sized from the stored film size, because the local film is gone by then.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from immich_memories.api.album_service import upload_waits
from immich_memories.api.film_relabel import RelabelOutcome, RelabelStatus
from immich_memories.config.loader import Config
from immich_memories.db import open_store
from immich_memories.operations.film_labelling import label_for_run
from immich_memories.tracking import RunDatabase

logger = logging.getLogger(__name__)


class RelabelRefused(Exception):
    """The run cannot be re-labelled; `status` is the HTTP answer the page shows."""

    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class RunRelabel:
    run_id: str
    outcome: RelabelOutcome


def relabel_run(
    config: Config, run_id: str, *, client: Any, db: RunDatabase | None = None
) -> RunRelabel:
    """Write the run's current label to the asset it was delivered as.

    Refuses, with the reason, an unknown run, a run never delivered to Immich, or a label that
    cannot be built. A film gone from Immich or a key without the rights is an outcome, not an
    exception: `--all` reports it and goes on.
    """
    db = db or RunDatabase(open_store(config))
    record = db.get_run(run_id)
    if record is None:
        raise RelabelRefused("Run not found. It may have been removed.", 404)
    asset_id = (record.immich_asset_id or "").strip()
    if not asset_id:
        raise RelabelRefused(
            "This run was never delivered to Immich, so there is no film there to re-label."
        )
    label = label_for_run(config, record, store=db.store)
    if label is None:
        raise RelabelRefused("The label for this run cannot be built.")
    outcome = client.relabel_film(
        asset_id, label, waits=upload_waits(record.output_size_bytes or 0)
    )
    return RunRelabel(run_id, outcome)


def relabel_all(config: Config, *, client: Any) -> list[RunRelabel]:
    """Re-label every run delivered to Immich; one that fails is reported and the rest go on."""
    db = RunDatabase(open_store(config))
    results = []
    for run_id in db.delivered_run_ids():
        try:
            results.append(relabel_run(config, run_id, client=client, db=db))
        except RelabelRefused as refusal:
            results.append(RunRelabel(run_id, RelabelOutcome(RelabelStatus.FAILED, str(refusal))))
        except Exception as exc:  # WHY: one film's Immich error must not stop the others
            logger.warning("Re-labelling %s failed: %s", run_id, type(exc).__name__)
            results.append(
                RunRelabel(
                    run_id,
                    RelabelOutcome(RelabelStatus.FAILED, f"Immich error ({type(exc).__name__})"),
                )
            )
    return results
