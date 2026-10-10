"""Remaining phase time from measured runs, separate from a stage's item counter."""

from __future__ import annotations

import time
from collections.abc import Mapping, Set
from typing import Any


class PhaseForecast:
    """A conditional sequence of phase budgets; None means no usable measurement.

    Durations come from live work rates and recorded runs, never percentage offsets. Returning to a phase
    reopens it and invalidates its old budget. A phase that outlives its reference is
    unknown too: zero seconds left would promise completion the producer has not reported.
    """

    def __init__(
        self,
        durations: Mapping[str, float | None],
        *,
        target: str,
        skipped: Set[str] = frozenset(),
    ) -> None:
        self._durations = dict(durations)
        self._skipped = set(skipped)
        self._elapsed: dict[str, float] = {}
        self._current: str | None = None
        self._started = 0.0
        self._target = target
        self._revision = 0
        self._finished = False
        self._measurement: tuple[float, float, bool] | None = None

    def enter(self, phase: str, *, now: float) -> None:
        """Advance or reopen a real phase; repeated activity keeps its original clock."""
        if phase == self._current:
            return
        self._close_current(now)
        self._measurement = None
        if phase not in self._durations:
            self._durations[phase] = None
        if phase in self._elapsed:
            self._durations[phase] = None
            self._revision += 1
        self._skipped.discard(phase)
        self._current, self._started = phase, now

    def invalidate(self, phase: str) -> None:
        """An unexpected pass invalidates only the affected phase's historical budget."""
        if self._durations.get(phase) is not None:
            self._durations[phase] = None
            self._revision += 1

    def measure_remaining(
        self, phase: str, remaining: float | None, *, now: float, partial: bool = False
    ) -> None:
        """Use this run's rate for known work, without claiming it covers an unknown phase."""
        if phase == self._current:
            self._measurement = (
                (max(0.0, remaining), now, partial) if remaining is not None else None
            )

    def complete_cut(self, *, now: float) -> None:
        """A saved cut finishes a cut-only job, while full generation continues."""
        if self._target == "cut":
            self.finish(now=now)

    def finish(self, *, now: float) -> None:
        """Only the owner that completed the operation can finish its forecast."""
        self._close_current(now)
        self._current = None
        self._finished = True

    def _close_current(self, now: float) -> None:
        if self._current is not None:
            self._elapsed[self._current] = self._elapsed.get(self._current, 0.0) + max(
                0.0, now - self._started
            )

    def snapshot(self, *, now: float) -> dict[str, Any]:
        """Expose the unknown portion instead of hiding measured time for the other phases."""
        keys = list(self._durations)
        current_index = keys.index(self._current) if self._current in keys else -1
        rows = [self._row(key, index, current_index, now) for index, key in enumerate(keys)]
        unknown = [row["key"] for row in rows if row["remaining_seconds"] is None]
        known = sum(row["known_remaining_seconds"] for row in rows)
        return {
            "target": self._target,
            "observed_at": time.time(),
            "phases": rows,
            "remaining_seconds": None if unknown else known,
            "known_remaining_seconds": known,
            "unknown_phases": unknown,
            "estimate_basis": self._estimate_basis(unknown),
            "revision": self._revision,
        }

    def _row(self, key, index, current_index, now) -> dict[str, Any]:
        elapsed = self._elapsed.get(key, 0.0)
        if key == self._current:
            elapsed += max(0.0, now - self._started)
        if key in self._skipped:
            state = "skipped"
        elif self._finished or 0 <= index < current_index:
            state = "completed"
        else:
            state = "running" if key == self._current else "pending"
        remaining, known = self._time_left(key, elapsed, now)
        if state in {"completed", "skipped"}:
            remaining, known = 0.0, 0.0
        return {
            "key": key,
            "state": state,
            "elapsed_seconds": elapsed,
            "remaining_seconds": remaining,
            "known_remaining_seconds": known,
        }

    def _time_left(self, key: str, elapsed: float, now: float) -> tuple[float | None, float]:
        if key == self._current and self._measurement is not None:
            seconds, observed, partial = self._measurement
            left = seconds - max(0.0, now - observed)
            return (None if partial or left <= 0 else left), max(0.0, left)
        duration = self._durations[key]
        remaining = None if duration is None or elapsed >= duration else duration - elapsed
        return remaining, remaining or 0.0

    def _estimate_basis(self, unknown: list[str]) -> str:
        if unknown:
            return "incomplete"
        if self._measurement is not None:
            return (
                "mixed"
                if any(value is not None for value in self._durations.values())
                else "current_run"
            )
        return "previous_run"


def forecast_at(record: dict | None, *, now: float | None = None) -> dict | None:
    """Age a saved estimate without treating elapsed wall time as newly completed work."""
    if record is None or record.get("observed_at") is None:
        return record
    now = time.time() if now is None else now
    age = max(0.0, now - record["observed_at"])
    rows = [dict(row) for row in record["phases"]]
    for row in rows:
        if row["state"] == "running":
            row["elapsed_seconds"] += age
            remaining = row.get("remaining_seconds")
            known = row.get("known_remaining_seconds", remaining or 0.0)
            row["known_remaining_seconds"] = max(0.0, known - age)
            row["remaining_seconds"] = (
                remaining - age if remaining is not None and remaining > age else None
            )
    unknown = [row["key"] for row in rows if row["remaining_seconds"] is None]
    known = sum(
        float(row.get("known_remaining_seconds", row["remaining_seconds"]) or 0.0) for row in rows
    )
    return record | {
        "observed_at": now,
        "phases": rows,
        "unknown_phases": unknown,
        "known_remaining_seconds": known,
        "remaining_seconds": None if unknown else known,
        "estimate_basis": "incomplete" if unknown else record["estimate_basis"],
    }
