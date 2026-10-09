"""The progress bar and phase log for a source stage that counts pictures."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.progress import TaskID

    from immich_memories.cli._live_display import ProgressDisplay

# A scheduled run's log shows a line at least this often, or after this many pictures.
PHASE_LOG_EVERY_SECONDS = 60.0
PHASE_LOG_EVERY_ITEMS = 25


class SourceProgressReporter:
    """A source stage owns the whole bar: counted when it reports numbers, a spinner when not.

    `on_phase` also hears the stage, throttled, so the phase log of a scheduled run does not
    go silent for the half hour a year's evidence takes. `on_activity` hears every update
    so a heartbeat can remember the latest count without writing each one to the store.
    """

    def __init__(
        self,
        progress: ProgressDisplay,
        task: TaskID,
        on_phase: Callable[[int, int, str], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        on_activity: Callable[[int, int, str], None] | None = None,
    ) -> None:
        self._progress = progress
        self._task = task
        self._mode: str | tuple | None = None
        self._on_phase = on_phase
        self._on_activity = on_activity
        self._clock = clock
        self._last_phase_time = 0.0
        self._last_phase_items = 0
        self._unbounded_label = ""

    def __call__(self, status: dict) -> None:
        if status.get("indeterminate"):
            self._unbounded_stage(status)
            return
        if "total_items" in status:
            self._counted_stage(status)
            return
        pct = status.get("overall_progress", 0)
        phase_name = status.get("current_phase", "")
        self._progress.update(
            self._task,
            completed=int(pct * 20),
            description=f"Analyzing: {phase_name}",
        )

    def _unbounded_stage(self, status: dict) -> None:
        label = status["phase_label"]
        if self._mode != "unbounded":
            self._progress.reset(self._task, total=None)
            self._mode = "unbounded"
        if label != self._unbounded_label:
            # Every uncounted stage says so, not only the first after a counted one: the
            # family-viewing check and the picture review follow each other (#2219).
            self._unbounded_label = label
            self._report(0, 0, label, new_stage=True)
        self._progress.update(self._task, description=status["phase_label"])
        if status.get("status") == "complete":
            self._progress.reset(self._task, total=100)

    def _counted_stage(self, status: dict) -> None:
        """Reset on a new stage even when it has the same number of items."""
        total = int(status["total_items"])
        self._unbounded_label = ""
        identity = status.get("stage_identity", (status.get("current_phase"), total))
        new_stage = self._mode != identity
        if new_stage:
            self._progress.reset(self._task, total=total)
            self._mode = identity
        description = status["phase_label"]
        done = int(status["current_index"])
        self._report(done, total, description, new_stage=new_stage)
        if remaining := status.get("remaining_label"):
            description += f" · {remaining}"
        self._progress.update(self._task, completed=done, description=description)

    def _report(self, done: int, total: int, label: str, *, new_stage: bool) -> None:
        if self._on_activity is not None:
            self._on_activity(min(done, total) if total else 0, total, label)
        if self._on_phase is None:
            return
        now = self._clock()
        due = (
            new_stage
            or now - self._last_phase_time >= PHASE_LOG_EVERY_SECONDS
            or done - self._last_phase_items >= PHASE_LOG_EVERY_ITEMS
        )
        if not due:
            return
        self._last_phase_time, self._last_phase_items = now, done
        self._on_phase(min(done, total) if total else 0, total, label)
