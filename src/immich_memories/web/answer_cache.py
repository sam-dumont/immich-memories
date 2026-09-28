"""Slow answers the pages ask for, kept on disk and refreshed behind them.

Suggestions and a year's trips each read the whole library window from Immich and take tens of
seconds; neither changes from one minute to the next. A page reads the last answer at once, with
when it was worked out, and the work runs again in the background when the answer is missing,
older than `max_age`, or somebody asked for a fresh one. One piece of work per key at a time.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from immich_memories.config_loader import Config
from immich_memories.security import sanitize_error_message

logger = logging.getLogger(__name__)

Compute = Callable[[], dict[str, Any]]


@dataclass(frozen=True)
class Cached:
    value: dict[str, Any] | None
    computed_at: datetime | None
    refreshing: bool
    error: str | None = None


def _in_a_thread(work: Callable[[], None]) -> None:
    threading.Thread(target=work, daemon=True).start()


# Process-wide, like the answers: two requests for one key share the one piece of work.
_RUNNING: set[str] = set()
_ERRORS: dict[str, str] = {}
_LOCK = threading.Lock()


class AnswerCache:
    def __init__(
        self,
        directory: Path,
        *,
        max_age: timedelta,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        start: Callable[[Callable[[], None]], None] = _in_a_thread,
    ) -> None:
        self._dir = directory
        self._max_age = max_age
        self._clock = clock
        self._start = start

    def _path(self, key: str) -> Path:
        return self._dir / f"{hashlib.sha256(key.encode()).hexdigest()[:24]}.json"

    def _load(self, key: str) -> tuple[dict[str, Any] | None, datetime | None]:
        try:
            stored = json.loads(self._path(key).read_text())
            return stored["value"], datetime.fromisoformat(stored["computed_at"])
        except (OSError, ValueError, KeyError):
            return None, None

    def read(self, key: str, compute: Compute, *, refresh: bool = False) -> Cached:
        """The last answer for `key`, starting fresh work when it is missing, stale or asked for."""
        value, computed_at = self._load(key)
        stale = computed_at is None or self._clock() - computed_at > self._max_age
        qualified = self._qualified(key)
        with _LOCK:
            running = qualified in _RUNNING
            if (stale or refresh) and not running:
                _RUNNING.add(qualified)
                running = True
                start = True
            else:
                start = False
        if start:
            self._start(lambda: self._work(key, compute))
        with _LOCK:
            if start and qualified not in _RUNNING:
                # The work already finished (a synchronous start): answer with its result.
                running = False
                value, computed_at = self._load(key)
            error = _ERRORS.get(qualified)
        return Cached(value, computed_at, running, error)

    def _qualified(self, key: str) -> str:
        return str(self._path(key))

    def _work(self, key: str, compute: Compute) -> None:
        qualified = self._qualified(key)
        try:
            value = compute()
        except Exception as error:  # noqa: BLE001 - the last answer stays; the page says why
            logger.warning("Refreshing %s failed: %s", key, error)
            with _LOCK:
                _ERRORS[qualified] = sanitize_error_message(str(error))
        else:
            self._dir.mkdir(parents=True, exist_ok=True)
            stored = {"computed_at": self._clock().isoformat(), "value": value}
            self._path(key).write_text(json.dumps(stored, default=str))
            with _LOCK:
                _ERRORS.pop(qualified, None)
        finally:
            with _LOCK:
                _RUNNING.discard(qualified)


def answer_cache(config: Config) -> AnswerCache:
    """The server's cache of slow answers, a day old at most."""
    return AnswerCache(config.cache.cache_path / "web-answers", max_age=timedelta(hours=24))
