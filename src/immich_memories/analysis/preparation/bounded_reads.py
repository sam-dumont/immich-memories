"""Per-picture Immich reads, a bounded few at a time, answered in the order asked (#2711).

A preview or a face read is one request whose time is almost all the server's. One at a
time, a cold year waits through every request in turn; a few in flight keep the server busy
without flooding it. The caller still handles each answer on its own thread, in input order,
so banking, progress and failures read exactly as they did one at a time.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import suppress
from typing import Any, TypeVar

_T = TypeVar("_T")

# How many reads each worker has queued between two cancellation checks.
_QUEUED_PER_WORKER = 4


def read_each(
    ids: Sequence[str],
    read: Callable[[str], _T],
    *,
    workers: int,
    check: Callable[[], None],
) -> Iterator[tuple[str, _T | None, Exception | None]]:
    """`(asset_id, answer, error)` for each id, in input order, at most `workers` in flight.

    `check` runs before each read one at a time, and before each queued wave otherwise, so a
    stop lands within a few reads. A read's exception is handed back, never raised here.
    """
    if workers <= 1:
        for asset_id in ids:
            check()
            yield _outcome(asset_id, read)
        return
    wave = workers * _QUEUED_PER_WORKER
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="immich-read") as pool:
        for start in range(0, len(ids), wave):
            check()
            batch = ids[start : start + wave]
            futures = [pool.submit(read, asset_id) for asset_id in batch]
            try:
                for asset_id, future in zip(batch, futures, strict=True):
                    yield _answer(asset_id, future)
            finally:
                for future in futures:
                    future.cancel()


def _outcome(asset_id: str, read: Callable[[str], _T]) -> tuple[str, _T | None, Exception | None]:
    try:
        return asset_id, read(asset_id), None
    except Exception as exc:  # WHY: handed back for the caller's own per-picture handling
        return asset_id, None, exc


def _answer(asset_id: str, future: Future[Any]) -> tuple[str, Any, Exception | None]:
    try:
        return asset_id, future.result(), None
    except Exception as exc:  # WHY: handed back for the caller's own per-picture handling
        return asset_id, None, exc


class ThreadClients:
    """One Immich client per thread for a bounded pool's reads.

    A `SyncImmichClient` runs one call at a time on its own event loop, so threads sharing
    one would only queue behind each other. The thread that builds this keeps `client`; any
    other thread gets the client's `sibling()` (same server, key and account routes, its
    own connections) on first use. `close` closes every sibling.
    """

    def __init__(self, client: Any) -> None:
        self._client = client
        self._owner = threading.get_ident()
        self._local = threading.local()
        self._lock = threading.Lock()
        self._opened: list[Any] = []

    @staticmethod
    def available(client: object) -> bool:
        """Whether `client` can open a sibling for another thread."""
        return callable(getattr(client, "sibling", None))

    def current(self) -> Any:
        """The calling thread's own client."""
        if threading.get_ident() == self._owner:
            return self._client
        mine = getattr(self._local, "client", None)
        if mine is None:
            mine = self._client.sibling()
            self._local.client = mine
            with self._lock:
                self._opened.append(mine)
        return mine

    def close(self) -> None:
        with self._lock:
            opened, self._opened = self._opened, []
        for client in opened:
            with suppress(Exception):  # WHY: closing a sibling cannot change what was read
                client.close()
