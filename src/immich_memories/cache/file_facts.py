"""Remember a costly fact about a file for as long as the file stays the same.

Some answers take a whole read of a large file: the digest of a 5 GB reader checkpoint,
the tempo of a bundled track (an ffmpeg decode). Each process used to work them out
again. Here they are kept in a small owner-only JSON file per kind, keyed by the file's
absolute path and its size, mtime and ctime, so a later process reuses the answer and a
file that was replaced or rewritten is worked out again.

The facts live under ~/.immich-memories/cache, the directory every deployment keeps
writable. When it is not writable the fact is still worked out; it is only not kept.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from immich_memories.security import write_secret_file

logger = logging.getLogger(__name__)

_Fact = TypeVar("_Fact", str, float)
# Enough for every checkpoint and bundled track an install has, with room for old ones.
_KEEP_AT_MOST = 256
_LOCK = threading.Lock()


def _store(kind: str) -> Path:
    return Path.home() / ".immich-memories" / "cache" / "file-facts" / f"{kind}.json"


def _signature(path: Path) -> list[int]:
    found = path.stat()
    return [found.st_size, found.st_mtime_ns, found.st_ctime_ns]


def _read(store: Path) -> dict:
    try:
        facts = json.loads(store.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return facts if isinstance(facts, dict) else {}


def remembered_fact(kind: str, path: Path, compute: Callable[[Path], _Fact | None]) -> _Fact | None:
    """``compute(path)``, worked out once per version of the file; None is never kept."""
    key = os.path.abspath(path)
    try:
        signature = _signature(path)
        store = _store(kind)
    except (OSError, RuntimeError):  # no file to sign, or no home to keep the fact in
        return compute(path)
    with _LOCK:
        known = _read(store).get(key)
    if isinstance(known, dict) and known.get("signature") == signature:
        return known.get("fact")
    fact = compute(path)
    if fact is not None:
        _keep(store, key, {"signature": signature, "fact": fact})
    return fact


def _keep(store: Path, key: str, entry: dict) -> None:
    with _LOCK:
        facts = _read(store)
        facts.pop(key, None)
        facts[key] = entry
        while len(facts) > _KEEP_AT_MOST:
            facts.pop(next(iter(facts)))
        try:
            write_secret_file(store, json.dumps(facts))
        except OSError as exc:
            logger.debug("Not keeping a file fact (%s): %s", store.name, type(exc).__name__)
