"""Prepared sources banked across runs, so a re-render prepares nothing twice (#2032).

A prepared source is what a run cuts or renders from one selected asset before
assembly: a stream-copied segment, a merged Live Photo, a photo's animated clip.
Making one costs a download of the original and often an encode. This bank keeps
each one under a caller-computed key, beside a small JSON record of its facts.

Each entry is two files in `entries/<key[:2]>/`:

- `<key>.<sha256[:16]><suffix>`: the media, named after its own bytes;
- `<key>.json`: the record, naming that media file and carrying its size,
  SHA-256 and the caller's facts.

Both are written to a temporary name and renamed into place, the media first.
Because the media name carries its digest, a reader that follows a record always
lands on the bytes that record describes, even while another process is writing
a new version of the same entry; at worst it reads the previous version whole.
A reader re-hashes what it takes, so a damaged entry is dropped and prepared
again, never handed out.

A taken entry becomes the caller's own file: a hard link where the filesystem
allows one, otherwise a copy. Evicting the bank entry later cannot pull a file
out from under a running assembly.

The size cap is `disk_budget`'s least-recently-used eviction: a take refreshes
the entry's mtime, and `begin_run` marks the moment after which entries are this
run's working set and may overflow the cap rather than disappear.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import shutil
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from immich_memories.cache.disk_budget import Eviction, evict_to_budget
from immich_memories.security import create_private_directory, write_secret_file

logger = logging.getLogger(__name__)

_RECORD_FORMAT = 1
_MEDIA_SUFFIXES = frozenset({".mp4", ".mov"})
# A temporary file nobody renamed for this long belongs to a killed run.
_PARTIAL_GRACE_SECONDS = 3600
_KEY_LENGTH = 64


@dataclass(frozen=True)
class BankedSource:
    """One verified entry, materialised as the caller's own file."""

    path: Path
    facts: Mapping[str, Any]


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _link_or_copy(source: Path, target: Path) -> None:
    """Hard link when source and target share a filesystem, copy otherwise."""
    try:
        os.link(source, target)
    except OSError as exc:
        if isinstance(exc, FileNotFoundError):
            raise
        shutil.copyfile(source, target)


def _temporary_sibling(path: Path) -> Path:
    return path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")


class PreparedSourceBank:
    """Keep prepared sources under content-and-recipe keys, inside a size cap."""

    def __init__(self, directory: Path, *, max_bytes: int) -> None:
        self.directory = directory
        self.max_bytes = max_bytes
        self._entries = directory / "entries"
        self._run_started_at: float | None = None
        self._tally = threading.Lock()
        self.taken = 0
        self.kept = 0
        create_private_directory(self._entries)

    def begin_run(self) -> None:
        """Sweep abandoned partial writes and protect what this run touches from here on."""
        cutoff = time.time() - _PARTIAL_GRACE_SECONDS
        for partial in self._entries.rglob(".*.tmp"):
            with contextlib.suppress(OSError):
                if partial.stat().st_mtime < cutoff:
                    partial.unlink()
        self._run_started_at = self._filesystem_now()

    def _filesystem_now(self) -> float:
        """Now, as this filesystem stamps a file: eviction compares against its mtimes."""
        marker = self.directory / ".run-started"
        try:
            marker.touch()
            return marker.stat().st_mtime
        except OSError:
            return time.time()

    def _shard(self, key: str) -> Path:
        if len(key) != _KEY_LENGTH or not all(char in "0123456789abcdef" for char in key):
            raise ValueError("a prepared-source key is a SHA-256 hex digest")
        return self._entries / key[:2]

    def _record(self, key: str) -> dict[str, Any] | None:
        record_path = self._shard(key) / f"{key}.json"
        try:
            record = json.loads(record_path.read_text())
        except (OSError, ValueError):
            return None
        if not isinstance(record, dict):
            return None
        media = record.get("media")
        valid = (
            record.get("format") == _RECORD_FORMAT
            and record.get("key") == key
            and isinstance(record.get("size"), int)
            and isinstance(record.get("sha256"), str)
            and isinstance(record.get("facts"), dict)
            and isinstance(media, str)
            and media == f"{key}.{record['sha256'][:16]}{Path(media).suffix}"
            and Path(media).suffix in _MEDIA_SUFFIXES
        )
        return record if valid else None

    def take(
        self,
        key: str,
        *,
        destination: Callable[[Mapping[str, Any]], Path],
        accept: Callable[[Mapping[str, Any]], bool] = lambda _facts: True,
    ) -> BankedSource | None:
        """Hand out a verified entry at ``destination(facts)``, or report a miss.

        ``accept`` sees the facts before any bytes move; a refused entry is a miss.
        """
        record = self._record(key)
        if record is None or not accept(record["facts"]):
            return None
        media = self._shard(key) / record["media"]
        target = destination(record["facts"])
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = _temporary_sibling(target)
        try:
            _link_or_copy(media, staged)
            intact = staged.stat().st_size == record["size"] and _sha256(staged) == record["sha256"]
        except OSError:
            staged.unlink(missing_ok=True)
            return None
        if not intact:
            staged.unlink(missing_ok=True)
            logger.warning("A banked prepared source was damaged; preparing it again")
            self._drop(key, record["media"])
            return None
        os.replace(staged, target)
        for path in (media, media.with_name(f"{key}.json")):
            with contextlib.suppress(OSError):
                os.utime(path)
        with self._tally:
            self.taken += 1
        return BankedSource(path=target, facts=record["facts"])

    def _drop(self, key: str, media_name: str) -> None:
        shard = self._shard(key)
        (shard / media_name).unlink(missing_ok=True)
        current = self._record(key)
        if current is None or current["media"] == media_name:
            (shard / f"{key}.json").unlink(missing_ok=True)

    def keep(self, key: str, source: Path, facts: Mapping[str, Any]) -> None:
        """Bank a fresh preparation. A failure costs the next run a preparation, nothing more."""
        suffix = source.suffix.lower()
        if suffix not in _MEDIA_SUFFIXES:
            return
        shard = self._shard(key)
        staged: Path | None = None
        try:
            create_private_directory(shard)
            digest = _sha256(source)
            size = source.stat().st_size
            media = shard / f"{key}.{digest[:16]}{suffix}"
            staged = _temporary_sibling(media)
            _link_or_copy(source, staged)
            os.replace(staged, media)
            record = {
                "format": _RECORD_FORMAT,
                "key": key,
                "media": media.name,
                "size": size,
                "sha256": digest,
                "facts": dict(facts),
            }
            write_secret_file(shard / f"{key}.json", json.dumps(record, sort_keys=True))
            with self._tally:
                self.kept += 1
        except OSError as exc:
            logger.debug("Could not bank a prepared source: %s", exc)
            if staged is not None:
                staged.unlink(missing_ok=True)

    def enforce_budget(self) -> Eviction:
        """Evict least recently used entries until the bank fits its cap."""
        eviction = evict_to_budget(
            self._entries, max_bytes=self.max_bytes, run_started_at=self._run_started_at
        )
        if eviction.overflowed:
            logger.warning(
                "This film's prepared sources are %.1f MB over the %.0f MB prepared-source "
                "cache. They stay for now, but the next run reclaims them, so rendering this "
                "selection again prepares them again. Raise "
                "advanced.analysis.prepared_source_cache_max_size_gb to keep them.",
                eviction.overflow_bytes / 1_000_000,
                self.max_bytes / 1_000_000,
            )
        return eviction
