"""Terminal wording for the same saved phase forecast the browser receives."""

from __future__ import annotations

from math import ceil

from immich_memories.tracking.phase_forecast import forecast_at

PHASE_NAMES = {
    "analysis": "Prepare pictures",
    "selection": "Select pictures",
    "download": "Prepare selected clips",
    "assembly": "Render film",
    "music": "Music",
    "check": "Check playback",
    "upload": "Upload film",
}


def duration(seconds: float) -> str:
    """Round an estimate rather than displaying false second-by-second precision."""
    return f"{ceil(seconds)}s" if seconds < 60 else f"{ceil(seconds / 60)} min"


def forecast_lines(forecast: dict) -> list[str]:
    """Show the whole estimate, its limits, and the state of every phase."""
    forecast = forecast_at(forecast) or forecast
    target = "film" if forecast["target"] == "film" else "cut"
    remaining = forecast.get("remaining_seconds")
    if remaining is not None:
        title = f"About {duration(remaining)} until the {target} is ready (measured estimate)"
    else:
        unknown = ", ".join(PHASE_NAMES.get(key, key) for key in forecast["unknown_phases"])
        known = forecast.get("known_remaining_seconds", 0)
        title = (
            f"About {duration(known)} of estimated work left; additional work unestimated: {unknown}"
            if known
            else f"Overall ETA not known yet; unmeasured: {unknown}"
        )
    return [title, *(_phase_line(phase) for phase in forecast["phases"])]


def _phase_line(phase: dict) -> str:
    line = f"{PHASE_NAMES.get(phase['key'], phase['key'])}: {phase['state']}"
    if phase["elapsed_seconds"]:
        line += f" · {duration(phase['elapsed_seconds'])} elapsed"
    if phase["state"] in {"pending", "running"}:
        left = phase.get("remaining_seconds")
        if left is not None:
            line += f" · ~{duration(left)} left"
        elif known := phase.get("known_remaining_seconds", 0):
            line += f" · ~{duration(known)} estimated, plus unmeasured work"
        else:
            line += " · time not known yet"
    return line
