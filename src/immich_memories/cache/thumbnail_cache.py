"""File-based thumbnail cache keyed by asset ID and size."""

from __future__ import annotations

import contextlib
import logging
import os
import threading
import time
from pathlib import Path

from immich_memories.cache.disk_budget import evict_to_budget
from immich_memories.security import create_private_directory

logger = logging.getLogger(__name__)

# What a path part may never hold: a separator or a parent step could leave the cache, and
# NUL ends the name early. Checked on the string, so a read costs no realpath() walk.
_UNSAFE_PARTS = ("/", "\\", "\0", "..")


def _safe_part(part: str) -> bool:
    return bool(part) and not any(unsafe in part for unsafe in _UNSAFE_PARTS)


class ThumbnailCache:
    """Simple file-based cache for Immich thumbnails."""

    # Until the tree has been measured, a put cannot know the total, so it asks
    # for a measurement every so often. That bounds the overshoot to roughly this
    # many files' worth of data, which at thumbnail sizes is a few MB.
    _PUTS_BETWEEN_BUDGET_CHECKS = 200

    def __init__(
        self, cache_dir: Path, max_size_mb: float = 30_000.0, *, namespace: str = ""
    ) -> None:
        if namespace and not _safe_part(namespace):
            raise ValueError("a cache namespace would escape the thumbnail cache")
        self.cache_dir = cache_dir
        self._namespace = namespace
        self.max_size_mb = max_size_mb
        self._puts_since_check = 0
        self._run_started_at: float | None = None
        self._overflow_announced = False
        # WHY: walking a 90k-file tree takes 20-45 s, so the budget check must cost what
        # the run wrote, not what the cache holds. The tree is measured once per run (the
        # first check after `begin_run`) and the total is kept in memory from there: puts
        # and `note_written` add, eviction resyncs it from its own walk. Another process
        # (web server and CLI share this directory) can make it drift; the next run's
        # measurement resyncs it, which is all a soft cap needs.
        self._tracked_bytes: int | None = None
        # Set once a pass found only this run's own files left to keep: re-walking
        # cannot free any of them, so later checks stop until the next run.
        self._nothing_left_to_free = False
        self._lock = threading.Lock()
        create_private_directory(self.cache_dir)
        self.cache_dir.chmod(0o700)

    def begin_run(self) -> None:
        """Mark everything written or read from here on as this run's working set.

        Callers that only report or clear the cache never call this, so the
        budget stays a plain cap for them. An analysis run does: it reads its
        previews back several times -- pixels, heads, contact sheets, captions
        -- and a preview evicted between those stages is recorded as a missing
        fact rather than re-fetched.
        """
        self._run_started_at = self._filesystem_now()
        self._overflow_announced = False
        with self._lock:
            self._tracked_bytes = None
            self._nothing_left_to_free = False

    def _filesystem_now(self) -> float:
        """Now, as this filesystem would stamp a file touched right here.

        Eviction spares an entry whose mtime is at or after the run started, and
        it reads that mtime back off this same filesystem. A filesystem that
        truncates timestamps to the second stamps a preview touched a moment
        from now *earlier* than a `time.time()` taken here, so the run evicts
        the very previews it is reading. Taking the boundary from a real file
        removes the mismatch, whatever the granularity is.
        """
        marker = self.cache_dir / ".run-started"
        try:
            marker.touch()
            return marker.stat().st_mtime
        except OSError:
            return time.time()

    def _path(self, asset_id: str, size: str) -> Path:
        subdir = asset_id[:2] if len(asset_id) >= 2 else "00"
        # Web requests keep the account set they began with, including late writes after
        # a settings change. Entries still share the same root and eviction budget.
        prefix = f"{self._namespace}-" if self._namespace else ""
        if not (_safe_part(asset_id) and _safe_part(size)):
            # WHY: the id came from a server response; the API models refuse a hostile
            # one at the parse, and this keeps every future caller inside the cache too.
            raise ValueError("an asset id would escape the thumbnail cache")
        return self.cache_dir / subdir / f"{prefix}{asset_id}_{size}.jpg"

    def get(self, asset_id: str, size: str) -> bytes | None:
        path = self._path(asset_id, size)
        try:
            with path.open("rb") as handle:
                data = handle.read()
                modified = os.fstat(handle.fileno()).st_mtime
        except OSError:
            return None
        # Eviction is oldest-mtime-first. Without this a thumbnail the run keeps
        # reading still looks as old as the moment it was written, so a working
        # set larger than the budget evicts its own live entries (#512). Within a
        # run, an entry stamped at or after its start is already spared, so only
        # the first read of an older one pays for the touch.
        if self._run_started_at is None or modified < self._run_started_at:
            with contextlib.suppress(OSError):
                os.utime(path)
        return data

    def put(self, asset_id: str, size: str, data: bytes) -> Path:
        path = self._path(asset_id, size)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            replaced = path.stat().st_size
        except OSError:
            replaced = 0
        path.write_bytes(data)
        self.note_written(len(data) - replaced)
        with self._lock:
            measured = self._tracked_bytes is not None
            self._puts_since_check += 1
            due = measured or self._puts_since_check >= self._PUTS_BETWEEN_BUDGET_CHECKS
        if due:
            self.enforce_budget()
        return path

    def note_written(self, delta_bytes: int) -> None:
        """Count bytes a writer put in the cache tree itself, bypassing `put`.

        Preparation writes previews straight into the cache layout; telling the
        cache what it added keeps the budget check off the disk.
        """
        with self._lock:
            if self._tracked_bytes is not None:
                self._tracked_bytes = max(0, self._tracked_bytes + delta_bytes)

    def enforce_budget(self) -> int:
        """Drop the least recently used thumbnails until the cache fits.

        Under budget this answers from the tracked total without touching the
        disk; the first call of a run (and any call over budget) walks the tree.
        """
        max_bytes = int(self.max_size_mb * 1_000_000) if self.max_size_mb != float("inf") else 0
        with self._lock:
            self._puts_since_check = 0
            if self.max_size_mb == float("inf") or self._nothing_left_to_free:
                return 0
            if self._tracked_bytes is not None and self._tracked_bytes <= max_bytes:
                return 0
        eviction = evict_to_budget(
            self.cache_dir,
            max_bytes=max_bytes,
            pattern="*.jpg",
            run_started_at=self._run_started_at,
        )
        with self._lock:
            self._tracked_bytes = eviction.remaining_bytes
            self._nothing_left_to_free = eviction.overflowed
        if eviction.overflowed and not self._overflow_announced:
            self._overflow_announced = True
            logger.warning(
                "This run needs more preview thumbnails than the cache budget holds: "
                "%d file(s) are %.1f MB over the %.0f MB limit. They stay on disk for "
                "this run, but the next run reclaims them, so an overlapping memory "
                "re-downloads every preview and re-captions the assets whose banked "
                "caption failure no longer matches. Raise "
                "cache.thumbnail_cache_max_size_mb -- budget roughly 0.35 MB per "
                "candidate asset a memory's scope can reach.",
                eviction.active_files,
                eviction.overflow_bytes / 1_000_000,
                self.max_size_mb,
            )
        return eviction.freed_bytes

    def clear(self) -> int:
        """Remove all cached thumbnails. Returns count of removed files."""

        self._run_started_at = None
        with self._lock:
            self._tracked_bytes = 0
            self._nothing_left_to_free = False
        count = 0
        if self.cache_dir.exists():
            for f in self.cache_dir.rglob("*.jpg"):
                f.unlink(missing_ok=True)
                count += 1
            # Clean empty subdirectories
            for d in sorted(self.cache_dir.rglob("*"), reverse=True):
                if d.is_dir():
                    with contextlib.suppress(OSError):
                        d.rmdir()
        return count

    def get_stats(self) -> dict:
        max_size_mb = self.max_size_mb
        if not self.cache_dir.exists():
            return {"file_count": 0, "total_size_bytes": 0, "max_size_mb": max_size_mb}

        files = list(self.cache_dir.rglob("*.jpg"))
        total_size = sum(f.stat().st_size for f in files)
        return {
            "file_count": len(files),
            "total_size_bytes": total_size,
            "max_size_mb": max_size_mb,
        }
