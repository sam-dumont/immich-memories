"""Choose measured phase budgets without exposing configured service addresses."""

from __future__ import annotations

from dataclasses import replace

from immich_memories.tracking.span_progress import SpanPlan
from immich_memories.tracking.timing import Collector

RENDER_PHASES = {
    "render.clip_extraction": "download",
    "render.assembly": "assembly",
    "render.music": "music",
    "render.playback_check": "check",
    "delivery": "upload",
}


def execution_profile(
    config, *, resolution: str | None = None, output_format: str | None = None
) -> dict:
    """Only categorical execution settings; no names, credentials or service URLs."""
    import platform

    return {
        "tier": config.tier,
        "worker": config.render.enabled,
        "machine": platform.machine(),
        "system": platform.system(),
        "resolution": config.output.resolution if resolution in {None, "auto"} else resolution,
        "format": {"mp4": "h264"}.get(output_format or "", output_format or config.output.codec),
        "quality": config.output.quality,
    }


def render_durations(
    history: Collector | None, *, items: int | None = None
) -> dict[str, float | None]:
    """Include playback validation and delivery; absent timings stay unknown."""
    spans = (
        [
            replace(span, name=RENDER_PHASES[span.name])
            for span in history.spans
            if span.name in RENDER_PHASES
        ]
        if history
        else []
    )
    measured = SpanPlan(spans, items=items)
    return {key: measured.weights.get(key) for key in RENDER_PHASES.values()}
