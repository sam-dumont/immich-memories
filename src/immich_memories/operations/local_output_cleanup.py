"""Remove a run's local film once Immich holds the durable copy.

`deliver_completed_artifact` calls this right after `run_tracker.mark_delivered`
persists a confirmed upload, and `runs upload` (CLI and web) after it records one.
From that point the local render exists only to
grow the output volume for no further use: the run record (and the Immich
asset it names) already survive it. `runs delete` shares the same directory
rule for an explicit, user-requested clear.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from immich_memories.tracking.models import RunMetadata

logger = logging.getLogger(__name__)


def local_output_directory(run: RunMetadata) -> Path | None:
    """The run-specific directory backing `run.output_path`, if it has one.

    `generate_memory` writes every film into `<output>/<slug>_<run_id>/`, one
    directory per run, and leftover intermediates (kept only with
    `--keep-intermediates`) live beside the film in that same directory --
    removing the directory removes both. A run whose output path predates
    that layout (its folder is not named `<slug>_<run_id>`) has only the file itself.
    """
    if not run.output_path:
        return None
    parent = Path(run.output_path).parent
    # The folder's own name, never the whole path: a folder further up that happens to
    # mention the run id is not this run's to delete.
    return parent if parent.name.endswith(f"_{run.run_id}") else None


def delete_local_output(run: RunMetadata) -> bool:
    """Delete the run's local film, and its work directory if it has one.

    Returns True if something was removed. Best-effort by design: the durable
    copy this is cleaning up after already exists elsewhere, so a failure here
    is logged by the caller rather than treated as breaking the delivery it
    follows.
    """
    directory = local_output_directory(run)
    if directory is not None:
        if not directory.exists():
            return False
        shutil.rmtree(directory)
        return True
    if not run.output_path:
        return False
    output_path = Path(run.output_path)
    if not output_path.is_file():
        return False
    output_path.unlink()
    return True


def remove_after_confirmed_upload(run: RunMetadata) -> bool:
    """Reclaim the local film once Immich confirms it; True when something was removed.

    The durable copy is already in Immich, so this is strictly best-effort: any
    failure leaves the file on disk for the next `runs delete`, rather than turning
    a confirmed upload into a reported failure.
    """
    try:
        removed = delete_local_output(run)
    except Exception:  # WHY: cleanup must never downgrade a confirmed delivery
        logger.warning("Could not remove local output after delivery", exc_info=True)
        return False
    if removed:
        logger.info("Removed local output for delivered run %s", run.run_id)
    return removed
