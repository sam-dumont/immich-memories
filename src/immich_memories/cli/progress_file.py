"""A JSON progress file a long command keeps for a watcher, such as the web client's job page."""

from __future__ import annotations

import json
import time
from pathlib import Path

from immich_memories.security import write_secret_file


def write_progress(path: Path | None, record: dict) -> None:
    """Replace the file with this record, whole: a reader never sees half of one."""
    if path is None:
        return
    try:
        previous = json.loads(path.read_text())
    except (OSError, ValueError):
        previous = {}
    if not isinstance(previous, dict):
        previous = {}
    if record.get("done"):
        record = previous | record
    stamp = time.time()
    payload = _with_history(record, previous, stamp)
    comparable = {key: value for key, value in previous.items() if key != "updated_at"}
    if payload == comparable:
        return
    # A forecast's elapsed clock can advance while the worker reports the same wait.
    # Save that clock without presenting the repeated wait as newly completed work.
    work = {
        key: value for key, value in payload.items() if key not in {"forecast", "remaining_seconds"}
    }
    old_work = {
        key: value
        for key, value in comparable.items()
        if key not in {"forecast", "remaining_seconds"}
    }
    updated = previous.get("updated_at", stamp) if work == old_work else stamp
    write_secret_file(path, json.dumps(payload | {"updated_at": updated}))


def _with_history(record: dict, previous: dict, stamp: float) -> dict:
    identity = (record.get("phase"), record.get("stage_name"), record.get("scope"))
    old_identity = (previous.get("phase"), previous.get("stage_name"), previous.get("scope"))
    changed = identity != old_identity
    fraction = record.get("stage_fraction")
    old_fraction = previous.get("stage_fraction")
    reset = fraction is not None and old_fraction is not None and fraction < old_fraction
    history = list(previous.get("stage_history", []))
    if previous and (changed or reset):
        history.append(
            {
                "label": str(previous.get("message") or previous.get("phase") or ""),
                "pass_id": previous.get("pass_id", 0),
                "scope": previous.get("scope", ""),
                "state": "previous",
            }
        )
    payload = record | {
        "stage_history": history[-24:],
        "pass_id": int(previous.get("pass_id", 0)) + int(changed or reset or not previous),
        "last_completed_at": previous.get("last_completed_at"),
    }
    if (
        not changed
        and fraction is not None
        and old_fraction is not None
        and fraction > old_fraction
    ):
        payload["last_completed_at"] = stamp
    return payload


def progress_writer(path: Path | None):
    # Imported once, as the command starts: a timing module that cannot load fails the render
    # before any work, never inside the engine's first progress report.
    from immich_memories.tracking.timing import active

    def report(phase: str, fraction: float, message: str) -> None:
        collected = active()
        estimate = collected.diagnostics.get("progress", {}) if collected else {}
        write_progress(
            path,
            {
                "done": False,
                "phase": phase,
                "fraction": fraction,
                "message": message,
                "scope": message if phase == "music" else "",
                "fraction_scope": "unknown",
                "stage_fraction": None,
                **estimate,
            },
        )

    return report if path is not None else None
