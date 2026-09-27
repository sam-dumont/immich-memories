"""One handle for a cut on both surfaces: the run id, resolved to its attempt directory.

The CLI files an attempt under a key built from the output name, the web UI under
a key built from the brief, so the same memory has two directories and neither
surface can find the other's. The run id is the one identity both surfaces
already print and store, so this index maps it to the attempt directory the run
selected from: `runs story <id>` and `runs why <asset>` read through it, and so
does the end-of-run summary.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from immich_memories.config_loader import Config

RUN_FILE = "run.private.json"
_INDEX_DIR = "by-run"


def _index_dir(cache_dir: Path) -> Path:
    return Path(cache_dir) / "editorial-runs" / _INDEX_DIR


def record_run_attempt(
    cache_dir: Path, run_id: str, attempt_dir: Path | str | None, output_path: Path | str
) -> None:
    """Remember which attempt a finished run selected from, on both sides of the link."""
    if not attempt_dir:
        return
    attempt = Path(attempt_dir)
    record = {"run_id": run_id, "attempt_dir": str(attempt), "output_path": str(output_path)}
    index = _index_dir(cache_dir)
    index.mkdir(parents=True, exist_ok=True)
    (index / f"{run_id}.json").write_text(json.dumps(record, indent=2) + "\n")
    if attempt.is_dir():
        (attempt / RUN_FILE).write_text(json.dumps(record, indent=2) + "\n")


def attempt_dir_for_run(cache_dir: Path, run_id: str) -> Path | None:
    """The attempt directory a run selected from, or None when the run left no record."""
    path = _index_dir(cache_dir) / f"{run_id}.json"
    if not path.is_file():
        return None
    try:
        attempt = Path(json.loads(path.read_text())["attempt_dir"])
    except (KeyError, ValueError, TypeError):
        return None
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


def record_cut_run(
    config: Config,
    attempt_dir: Path,
    *,
    memory_type: str | None,
    memory_key: str | None,
    date_range: tuple[date, date] | None,
    people: tuple[str, ...] = (),
    person_name: str | None = None,
    source: str = "manual",
    clips_selected: int = 0,
    target_duration_seconds: float | None = None,
) -> str:
    """Record a finished cut that stopped before rendering as a run of its own.

    The run has no film yet. It can be read (`runs story`), revised in the web client and
    rendered (`runs render`); each render is then a film run on this same attempt.
    """
    from immich_memories.tracking import RunDatabase
    from immich_memories.tracking.models import RunMetadata
    from immich_memories.tracking.run_id import generate_run_id

    now = datetime.now(UTC)
    run_id = generate_run_id(now)
    RunDatabase(config.cache.database_path).save_run(
        RunMetadata(
            run_id=run_id,
            created_at=now,
            completed_at=now,
            status="completed",
            memory_type=memory_type,
            memory_key=memory_key,
            memory_people=people,
            person_name=person_name,
            source=source,
            date_range_start=date_range[0] if date_range else None,
            date_range_end=date_range[1] if date_range else None,
            clips_selected=clips_selected,
            target_duration_seconds=int(target_duration_seconds or 0),
        )
    )
    record_run_attempt(config.cache.cache_path, run_id, attempt_dir, "")
    return run_id
