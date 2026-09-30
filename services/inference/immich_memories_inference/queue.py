"""Visible FIFO model waits that do not occupy native inference workers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass, field
from time import monotonic
from typing import TypeVar

T = TypeVar("T")


class QueueFull(RuntimeError):
    """No waiting capacity remains; the caller can retry later."""


@dataclass
class _Lane:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending: dict[object, float] = field(default_factory=dict)
    active: int = 0
    started: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0
    rejected: int = 0
    executed: int = 0
    wait_seconds: float = 0.0
    run_seconds: float = 0.0

    def snapshot(self, now: float, uptime: float) -> dict[str, int | float]:
        return {
            "queued": len(self.pending),
            "active": self.active,
            "completed": self.completed,
            "failed": self.failed,
            "cancelled": self.cancelled,
            "rejected": self.rejected,
            "oldest_wait_seconds": max((now - at for at in self.pending.values()), default=0),
            "mean_wait_seconds": self.wait_seconds / self.started if self.started else 0,
            "mean_run_seconds": self.run_seconds / self.executed if self.executed else 0,
            "completed_per_second": self.completed / uptime if uptime else 0,
        }


class InferenceQueue:
    """One FIFO lane per model, sharing the configured native worker limit."""

    def __init__(
        self, names: tuple[str, ...], pool: ThreadPoolExecutor, workers: int, max_queued: int
    ) -> None:
        self._lanes = {name: _Lane() for name in names}
        self._pool = pool
        self._capacity = asyncio.Semaphore(workers)
        self._since = monotonic()
        self._max_queued = max_queued

    def snapshot(self) -> dict[str, object]:
        now = monotonic()
        uptime = now - self._since
        return {
            "uptime_seconds": uptime,
            "capacity": self._max_queued,
            "producers": {name: lane.snapshot(now, uptime) for name, lane in self._lanes.items()},
        }

    async def run(self, name: str, call: Callable[[], T]) -> T:
        lane = self._lanes[name]
        if sum(len(state.pending) for state in self._lanes.values()) >= self._max_queued:
            lane.rejected += 1
            raise QueueFull(f"Inference queue is full; retry {name} later")
        ticket = object()
        lane.pending[ticket] = monotonic()
        try:
            async with lane.lock, self._capacity:
                lane.wait_seconds += monotonic() - lane.pending.pop(ticket)
                lane.started += 1
                return await self._execute(lane, call)
        except asyncio.CancelledError:
            lane.cancelled += 1
            raise
        finally:
            lane.pending.pop(ticket, None)

    async def _execute(self, lane: _Lane, call: Callable[[], T]) -> T:
        lane.active = 1
        started = monotonic()
        work = asyncio.get_running_loop().run_in_executor(self._pool, call)
        try:
            result = await asyncio.shield(work)
            lane.completed += 1
            return result
        except asyncio.CancelledError:
            # Native work keeps running: retain its lane until it actually stops.
            with suppress(Exception):
                await work
            raise
        except Exception:
            lane.failed += 1
            raise
        finally:
            lane.active = 0
            lane.executed += 1
            lane.run_seconds += monotonic() - started
