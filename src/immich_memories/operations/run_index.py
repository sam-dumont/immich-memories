"""One handle for a cut on both surfaces: the run id, resolved to its attempt directory.

The CLI files an attempt under a key built from the output name, the web UI under
a key built from the brief, so the same memory has two directories and neither
surface can find the other's. The run id is the one identity both surfaces
already print and store, so the store's `run_attempts` table maps it to the attempt
directory the run selected from: `runs story <id>` and `runs why <asset>` read through
it, and so does the end-of-run summary. The attempt's own `run.private.json` is the
link the other way, and stays a file beside the attempt.
"""

from __future__ import annotations

import json
from pathlib import Path

import sqlalchemy as sa

from immich_memories.db import Store, now_db, open_store, upsert
from immich_memories.db.tables import run_attempts

RUN_FILE = "run.private.json"


def record_run_attempt(
    run_id: str,
    attempt_dir: Path | str | None,
    output_path: Path | str,
    *,
    store: Store | None = None,
) -> None:
    """Remember which attempt a finished run selected from, on both sides of the link."""
    if not attempt_dir:
        return
    attempt = Path(attempt_dir)
    record = {"run_id": run_id, "attempt_dir": str(attempt), "output_path": str(output_path)}
    with (store or open_store()).begin() as conn:
        upsert(conn, run_attempts, [record | {"recorded_at": now_db()}], ["run_id"])
    if attempt.is_dir():
        (attempt / RUN_FILE).write_text(json.dumps(record, indent=2) + "\n")


def attempt_dir_for_run(run_id: str, *, store: Store | None = None) -> Path | None:
    """The attempt directory a run selected from, or None when the run left no record."""
    with (store or open_store()).connect() as conn:
        recorded = conn.execute(
            sa.select(run_attempts.c.attempt_dir).where(run_attempts.c.run_id == run_id)
        ).scalar()
    if recorded is None:
        return None
    attempt = Path(recorded)
    return attempt if attempt.is_dir() else None


def run_id_for_attempt(attempt_dir: Path) -> str | None:
    """The run id a finished attempt was rendered under, if the run got that far."""
    path = Path(attempt_dir) / RUN_FILE
    if not path.is_file():
        return None
    try:
        return str(json.loads(path.read_text())["run_id"])
    except (KeyError, ValueError, TypeError):
        return None


_LEVEL_WORDS = {"just_us": "just us", "family": "family", "shareable": "shareable"}


def sharing_line(attempt_dir: Path | None) -> str:
    """Who the attempt's cut was made for, in reader words; empty when there is no attempt.

    A cut from before sharing levels existed was cut for the family.
    """
    if attempt_dir is None:
        return ""
    try:
        status = json.loads((Path(attempt_dir) / "status.private.json").read_text())
    except (OSError, ValueError):
        status = {}
    request = status.get("request") if isinstance(status, dict) else None
    level = request.get("audience", "family") if isinstance(request, dict) else "family"
    return f"Sharing: {_LEVEL_WORDS.get(level, level)}"
