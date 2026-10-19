"""Reuse the exact duplicate hash without decoding unchanged preview bytes again."""

from __future__ import annotations

import hashlib
import threading
import time
import weakref
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

from immich_memories.analysis.corpus.duplicate_hashing import compute_thumbnail_hash
from immich_memories.cache.sqlite_conn import ThreadOwnedConnections

METHOD = f"thumbnail-ahash-v1-bgr-gray-area-opencv-{cv2.__version__}-numpy-{np.__version__}"
_SCHEMA = """CREATE TABLE IF NOT EXISTS thumbnail_hashes (
    source_key TEXT PRIMARY KEY, thumbnail_hash TEXT NOT NULL
)"""


# Hashes this process already worked out, per bank file, by source key (the method, the
# hash size and the preview's own bytes, so a preview that changes is a new key). A film
# builds its material twice, draft then refinement, each with a hasher of its own over the
# same pool: the second one answers here instead of asking SQLite again. Bounded, because
# the web server lives for weeks; a year's pool is a few thousand previews.
_REMEMBERED: dict[Path, OrderedDict[str, str]] = {}
_REMEMBERED_LOCK = threading.Lock()
_REMEMBER_AT_MOST = 50_000
# New hashes are written this many at a time, and the rest when the hasher closes: a
# commit per row was most of a cold pass. A row lost to a crash is only computed again.
_BANK_EVERY = 64


def _bank(connections: ThreadOwnedConnections, pending: list[tuple[str, str]]) -> None:
    rows, pending[:] = pending.copy(), []
    if not rows:
        return
    with connections.connection() as connection:
        connection.executemany("INSERT OR REPLACE INTO thumbnail_hashes VALUES (?, ?)", rows)
        connection.commit()


class CachedThumbnailHasher:
    """A preview's contents, hash size and implementation identify its reusable fact."""

    def __init__(
        self,
        cache_path: Path,
        read_preview: Callable[[str], bytes | None],
        *,
        hash_size: int = 8,
    ) -> None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.touch(mode=0o600, exist_ok=True)
        cache_path.chmod(0o600)
        self._connections = ThreadOwnedConnections(cache_path, _SCHEMA)
        self._read_preview = read_preview
        self._hash_size = hash_size
        self._method = METHOD
        self._counts: dict[str, int] = {
            "requests": 0,
            "cache_hits": 0,
            "memory_hits": 0,
            "hashes_computed": 0,
            "unavailable": 0,
            "preview_bytes": 0,
        }
        self._wall_seconds = 0.0
        with _REMEMBERED_LOCK:
            self._remembered = _REMEMBERED.setdefault(cache_path.resolve(), OrderedDict())
        self._pending: list[tuple[str, str]] = []
        self._pending_lock = threading.Lock()
        # A hasher nobody closes still banks what it computed, when it goes or the process ends.
        weakref.finalize(self, _bank, self._connections, self._pending)

    def __call__(self, asset_id: str) -> str | None:
        started = time.monotonic()
        self._counts["requests"] += 1
        try:
            payload = self._read_preview(asset_id)
            if not payload:
                self._counts["unavailable"] += 1
                return None
            self._counts["preview_bytes"] += len(payload)
            value = self._hash_of(payload)
            if not value:
                self._counts["unavailable"] += 1
                return None
            return value
        finally:
            self._wall_seconds += time.monotonic() - started

    def _hash_of(self, payload: bytes) -> str | None:
        digest = hashlib.sha256(f"{METHOD}\0{self._hash_size}\0".encode())
        digest.update(payload)
        key = digest.hexdigest()
        with _REMEMBERED_LOCK:
            known = self._remembered.get(key)
        if known is not None:
            self._counts["cache_hits"] += 1
            self._counts["memory_hits"] += 1
            return known
        value = self._banked(key)
        if value is not None:
            self._counts["cache_hits"] += 1
        else:
            value = compute_thumbnail_hash(payload, self._hash_size) or None
            self._counts["hashes_computed"] += 1
            if value is None:
                return None
            self._queue(key, value)
        self._remember(key, value)
        return value

    def _banked(self, key: str) -> str | None:
        with self._connections.connection() as connection:
            row = connection.execute(
                "SELECT thumbnail_hash FROM thumbnail_hashes WHERE source_key=?", (key,)
            ).fetchone()
        return None if row is None else str(row[0])

    def _remember(self, key: str, value: str) -> None:
        with _REMEMBERED_LOCK:
            self._remembered[key] = value
            if len(self._remembered) > _REMEMBER_AT_MOST:
                self._remembered.popitem(last=False)

    def _queue(self, key: str, value: str) -> None:
        with self._pending_lock:
            self._pending.append((key, value))
            if len(self._pending) >= _BANK_EVERY:
                _bank(self._connections, self._pending)

    def metrics(self) -> dict:
        reported: dict[str, object] = {"method": self._method, "hash_size": self._hash_size}
        reported.update(self._counts)
        reported["wall_seconds"] = round(self._wall_seconds, 3)
        return reported

    def close(self) -> None:
        with self._pending_lock:
            _bank(self._connections, self._pending)
        self._connections.close()
