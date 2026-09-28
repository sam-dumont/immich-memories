"""How a run reports its progress: the outer lifecycle and the inner scale.

These are adapters between the pipeline's own progress and whatever callbacks a
caller supplied. None of the generation logic needs to see them, and generate.py
was at the 1000-line gate, so they live beside it like the other generate_*
modules.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from immich_memories.operations.phases import OperationalPhase, PhaseEvent

if TYPE_CHECKING:
    from immich_memories.generate import GenerationParams
    from immich_memories.tracking.run_tracker import RunTracker

logger = logging.getLogger(__name__)


def _report(params: GenerationParams, phase: str, progress: float, msg: str) -> None:
    if params.progress_callback:
        params.progress_callback(phase, progress, msg)


def emit_operational_phase(
    params: GenerationParams,
    run_tracker: RunTracker,
    phase: OperationalPhase,
    *,
    current: int,
    total: int,
    message: str,
    elapsed_seconds: float = 0.0,
) -> PhaseEvent:
    """Publish and persist an outer phase without making telemetry job-critical."""
    event = PhaseEvent(phase, current, total, message, elapsed_seconds)
    try:
        run_tracker.record_phase_event(event)
    except Exception:  # WHY: extension trackers must not make status telemetry fatal
        logger.warning("Could not persist operational phase '%s'", phase.value)
    if params.phase_callback is not None:
        try:
            params.phase_callback(event)
        except Exception:  # WHY: observer failures cannot invalidate completed pipeline work
            logger.warning("Operational phase observer failed for '%s'", phase.value)
    return event


class _OperationalProgress:
    """Emit one monotonic outer lifecycle around generation internals."""

    def __init__(self, params: GenerationParams, run_tracker: RunTracker) -> None:
        self._params = params
        self._run_tracker = run_tracker
        self._started = time.monotonic()
        self._last_phase: OperationalPhase | None = None

    def emit(
        self,
        phase: OperationalPhase,
        current: int,
        total: int,
        message: str,
    ) -> PhaseEvent:
        now = time.monotonic()
        event = emit_operational_phase(
            self._params,
            self._run_tracker,
            phase,
            current=current,
            total=total,
            message=message,
            elapsed_seconds=now - self._started,
        )
        self._started = now
        self._last_phase = phase
        return event

    def emit_unperformed_prerequisites(self, through: OperationalPhase) -> None:
        """Mark only prerequisites not owned by this generation call as complete."""
        completed = self._params.completed_operational_phase
        messages = {
            OperationalPhase.DISCOVERY: "Discovery not required",
            OperationalPhase.DOWNLOAD: "Downloads already prepared",
            OperationalPhase.ANALYSIS: "Analysis already prepared",
            OperationalPhase.SELECTION: "Selection already prepared",
        }
        for phase, message in messages.items():
            if (
                phase.order <= through.order
                and (completed is None or phase.order > completed.order)
                and (self._last_phase is None or phase.order > self._last_phase.order)
            ):
                self.emit(phase, 0, 0, message)

    def phase_is_unperformed(self, phase: OperationalPhase) -> bool:
        completed = self._params.completed_operational_phase
        return completed is None or phase.order > completed.order


class _PipelineProgress:
    """Maps per-phase 0.0-1.0 progress into the overall pipeline range.

    Each phase gets a proportional slice of 0.0-1.0 based on estimated
    wall-clock time. All progress reports go through this to ensure the
    bar only moves forward, never jumps backward.
    """

    def __init__(self, params: GenerationParams, clip_count: int) -> None:
        self._params = params
        from immich_memories.db import open_store
        from immich_memories.tracking.span_progress import SpanPlan
        from immich_memories.tracking.span_store import SpanStore

        history = SpanStore(open_store(params.config)).latest(params.source, prefix="render.")
        names = {
            "render.clip_extraction": "download",
            "render.assembly": "assembly",
            "render.music": "music",
            "delivery": "upload",
        }
        from dataclasses import replace

        spans = (
            [replace(span, name=names[span.name]) for span in history.spans if span.name in names]
            if history
            else []
        )
        self._plan = SpanPlan(spans, items=clip_count)
        self._last = 0.0
        self.remaining_seconds: float | None = None
        self._phase = ""
        self._phase_started = 0.0

    def report(self, phase: str, pct: float, msg: str) -> None:
        """Report one total from history; the first run promises no percentage or ETA."""
        from immich_memories.tracking.timing import active

        if not self._params.progress_callback:
            return
        name = "download" if phase == "extract" else phase
        now = time.monotonic()
        if name != self._phase:
            self._phase, self._phase_started = name, now
        remaining = (now - self._phase_started) * (1 - pct) / pct if 0 < pct < 1 else None
        estimate = self._plan.estimate(name, fraction=pct, remaining=remaining)
        if estimate:
            self._last = max(self._last, min(0.99, estimate.fraction))
        if phase == "done":
            self._last = 1.0
        self.remaining_seconds = estimate.remaining_seconds if estimate else None
        if collected := active():
            collected.diagnostics["progress"] = {
                "fraction": self._last if self._plan.weights or phase == "done" else None,
                "remaining_seconds": self.remaining_seconds,
            }
        self._params.progress_callback(phase, self._last, msg)

    def assembly_callback(self) -> Callable[[float, str], None] | None:
        """Create a 2-arg callback for assemble_with_titles."""
        if not self._params.progress_callback:
            return None

        def cb(pct: float, msg: str) -> None:
            self.report("assembly", pct, msg)

        return cb
