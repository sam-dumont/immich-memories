"""The length a memory type asks for before discovery has seen a picture.

One resolver for every surface: the CLI calls it when ``--duration`` is absent,
and the web UI runs the CLI's ``generate`` without a duration for an
auto-length cut. A second copy of this table somewhere else is how a season
came out 2 min 15 s in one place and 3 min 15 s in the other.
"""

from __future__ import annotations

from calendar import monthrange

from immich_memories.planning.auto_duration import trip_editorial_duration_seconds
from immich_memories.timeperiod import DateRange


def duration_from_date_range(date_range: DateRange) -> float:
    """Scale duration by date range: 1 month = 60s, 1 year = 600s.

    Quadratic curve fitted through (1mo, 60s), (6mo, 360s), (12mo, 600s).
    Linear ~60s/month for the first half, then decelerates toward 600s. A full
    season lands near 195s. Also the fallback for a span no type claims.
    """
    months = max(1, (date_range.end - date_range.start).days + 1) / 30.0
    duration = (-20 * months**2 + 800 * months - 120) / 11
    return float(max(30, min(600, duration)))


def _recap_duration_from_date_range(date_range: DateRange) -> float:
    """Give recap/person scopes one minute per month, capped at ten minutes."""
    start = date_range.start.date()
    end = date_range.end.date()
    complete_calendar_months = start.day == 1 and end.day == monthrange(end.year, end.month)[1]
    months = (
        (end.year - start.year) * 12 + end.month - start.month + 1
        if complete_calendar_months
        else ((date_range.end - date_range.start).days + 1) / 30.0
    )
    return float(max(30, min(600, months * 60)))


# WHY these by name: duration_from_date_range's curve was fitted on 1-12
# months and is wrong at both ends. Past ~40 months it turns negative, so five
# Christmases clamped to the same 30s floor as an empty weekend (#511); at a
# one-day span it evaluates negative too, so a special day would render as 30
# seconds however much happened on it. Their presets already state the length
# they want, so the resolver reads that instead.
_PRESET_DURATION_TYPES = ("holiday", "special_day")


def _preset_duration(memory_type: str, preset_params: dict | None = None) -> float | None:
    """The registered preset's own intended length for a memory type."""
    from immich_memories.memory_types.factory import create_preset
    from immich_memories.memory_types.registry import MemoryType

    preset = create_preset(MemoryType(memory_type), **(preset_params or {}))
    return preset.default_duration_seconds


def default_duration_for_type(
    memory_type: str | None,
    date_range: DateRange | None,
    preset_params: dict | None = None,
    primary_window: DateRange | None = None,
) -> float | None:
    """The seconds a memory type asks for when nobody gave a length.

    Recap and person types scale at 1 minute per month up to 10 minutes.
    Season follows the date-range curve (~195s for a full season). Trip dates provide an
    editorial estimate; discovered media later applies the capacity cap.
    Types the span curve cannot reach -- several years at one end, a single day
    at the other -- take the length their preset asks for.
    Other fixed types: on_this_day (45s), person without range (120s).

    ``preset_params`` is forwarded to the preset factory for the types whose
    length depends on more than the dates: a special day needs the day it
    happened on and how long it stayed awake.

    ``primary_window`` is the window a memory is actually made of, when that is
    narrower than the span it displays. A birthday memory shows decades but is
    made from a rolling year (#511, #719).
    """
    if not memory_type:
        return None

    if memory_type == "on_this_day":
        return 45.0
    if memory_type == "monthly_highlights":
        return 60.0
    if memory_type in _PRESET_DURATION_TYPES:
        return _preset_duration(memory_type, preset_params)
    if memory_type == "trip" and date_range is not None:
        days = max(1, (date_range.end - date_range.start).days + 1)
        return trip_editorial_duration_seconds(days)
    if memory_type in ("person_spotlight", "multi_person"):
        if date_range is None:
            return 120.0
        return _recap_duration_from_date_range(primary_window or date_range)
    if memory_type == "year_in_review" and date_range is not None:
        return _recap_duration_from_date_range(date_range)

    # Everything else: scale by date range
    if date_range is not None:
        return duration_from_date_range(date_range)
    return None
