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
    _notify_phase(params, event)
    return event


def _notify_phase(params: GenerationParams, event: PhaseEvent) -> None:
    if params.phase_callback is not None:
        try:
            params.phase_callback(event)
        except Exception:  # WHY: observer failures cannot invalidate completed pipeline work
            logger.warning("Operational phase observer failed for '%s'", event.phase.value)


def render_progress_events(
    inner: Callable[[float, str], None] | None,
    operational: _OperationalProgress,
    total: int,
    *,
    clock: Callable[[], float] = time.monotonic,
    every_seconds: float = 30.0,
) -> Callable[[float, str], None]:
    """Report render activity without converting encoder time into completed clip counts.

    The assembler also reports audio mixing and muxing on this callback. Its fraction
    cannot say how many clips are finished, so phase events leave the counts unknown.
    """
    last = float("-inf")

    def report(pct: float, msg: str) -> None:
        nonlocal last
        if inner is not None:
            inner(pct, msg)
        now = clock()
        current = 0
        if now - last < every_seconds:
            operational.observe(OperationalPhase.RENDER, current, 0, msg)
            return
        last = now
        operational.emit(OperationalPhase.RENDER, current, 0, msg)

    return report


# Extraction reports its own fraction of the clip work as 0 to this, the rest being the download.
_EXTRACT_SHARE = 0.7


def clip_preparation_events(
    inner: Callable[[str, float, str], None] | None,
    operational: _OperationalProgress,
    phase: OperationalPhase,
    total: int,
    *,
    clock: Callable[[], float] = time.monotonic,
    every_seconds: float = 30.0,
) -> Callable[[str, float, str], None]:
    """Report every completed source; throttle only repeats of an unchanged count.

    Without it the phase stays on the last thing reported before extraction (the finished
    selection) for the whole download and cut, and a scheduled run's log and the trigger API
    keep saying so (#2243).
    """
    last = float("-inf")
    last_count = -1

    def report(stage: str, pct: float, msg: str) -> None:
        nonlocal last, last_count
        if inner is not None:
            inner(stage, pct, msg)
        if stage != "extract":
            return
        now = clock()
        done = min(total, int(pct / _EXTRACT_SHARE * total + 0.5))
        if done == last_count and now - last < every_seconds:
            return
        last, last_count = now, done
        operational.emit(phase, done, total, f"Preparing clips ({done}/{total})")

    return report


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

    def observe(self, phase: OperationalPhase, current: int, total: int, message: str) -> None:
        """Keep live observers current between persisted phase events."""
        _notify_phase(self._params, PhaseEvent(phase, current, total, message, 0.0))

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
        from immich_memories.tracking import timing
        from immich_memories.tracking.forecast_reference import execution_profile, render_durations
        from immich_memories.tracking.span_progress import SpanPlan
        from immich_memories.tracking.span_store import SpanStore

        profile = execution_profile(
            params.config, resolution=params.output_resolution, output_format=params.output_format
        )
        history = SpanStore(open_store(params.config)).latest(
            params.source,
            prefix="render.",
            profile=profile,
        )
        if collected := timing.active():
            collected.diagnostics["progress_profile"] = profile
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
        # WHY: rough relative durations keep a first run's bar moving; measured stages
        # replace them once a completed run exists. Zero marks a phase this run skips.
        defaults = {
            "download": clip_count * 3.0 + 20.0,
            "assembly": 180.0 + clip_count * 8.0,
            "music": 0.0 if params.no_music else 120.0,
            "upload": 30.0 if params.upload_enabled else 0.0,
        }
        self._plan = SpanPlan(spans, items=clip_count, defaults=defaults)
        from immich_memories.tracking.phase_forecast import PhaseForecast

        durations = render_durations(history, items=clip_count)
        skipped = set()
        if params.no_music:
            skipped.add("music")
        if not params.upload_enabled:
            skipped.add("upload")
        if params.config.render.enabled:
            skipped.add("download")  # Worker owns preparation inside render.assembly.
        collected = timing.active()
        self._forecast = (collected.forecast if collected else None) or PhaseForecast(
            durations,
            target="film",
            skipped=skipped,
        )
        if collected:
            collected.forecast = self._forecast
        self._last = 0.0
        self.remaining_seconds: float | None = None
        self._phase = ""
        self._phase_started = 0.0

    def report(self, phase: str, pct: float, msg: str) -> None:
        """Report one monotonic total; an ETA only once history measured what is left."""
        from immich_memories.tracking.timing import active, clock

        name = "download" if phase == "extract" else phase
        now = clock()
        if name != self._phase:
            self._phase, self._phase_started = name, now
        remaining = (now - self._phase_started) * (1 - pct) / pct if 0 < pct < 1 else None
        estimate = self._plan.estimate(name, fraction=pct, remaining=remaining)
        if estimate:
            self._last = max(self._last, min(0.99, estimate.fraction))
        if phase == "done":
            self._last = 1.0
        # Legacy callbacks keep their monotonic display scale. It contains fixed phase
        # shares (music, mux, upload), not enough measured work for a current-stage ETA.
        canonical = "assembly" if phase.startswith("worker_") else name
        if phase == "done":
            self._forecast.finish(now=now)
        elif canonical in {"download", "assembly", "music", "check", "upload"}:
            self._forecast.enter(canonical, now=now)
            self._forecast.measure_remaining(
                canonical, remaining if phase == "worker_download" else None, now=now, partial=True
            )
        forecast = self._forecast.snapshot(now=now)
        self.remaining_seconds = forecast["remaining_seconds"]
        if collected := active():
            collected.diagnostics["progress"] = {
                "forecast": forecast,
                "fraction": self._last,
                "remaining_seconds": self.remaining_seconds,
                "fraction_scope": "stage" if phase == "worker_download" else "unknown",
                "stage_fraction": pct if phase == "worker_download" else None,
            }
        if self._params.progress_callback:
            self._params.progress_callback(phase, self._last, msg)

    def assembly_callback(self) -> Callable[[float, str], None] | None:
        """Create a 2-arg callback for assemble_with_titles."""
        if not self._params.progress_callback:
            return None

        def cb(pct: float, msg: str) -> None:
            self.report("assembly", pct, msg)

        return cb
