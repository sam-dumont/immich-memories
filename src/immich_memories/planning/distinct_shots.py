"""The one rule for counting a further frame as its own shot (#2083).

Shared by the depth fill (`editorial_story_depth_fill`), which spends a film's free
content seconds on further frames of the moments it already shows, and the duration
decision (`auto_duration`), which sizes a day's share of a film's length from how much
distinct material the day actually holds. Both must agree on what counts: a video is its
own shot when its window does not overlap one already kept; anything else is its own shot
only once it is a real five minutes from every kept shot of the same capture context. A
heap of frames sharing one timestamp -- a placeholder date, a burst, a pile of scans -- is
one shot, not many.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

# The five-minute capture-group spacing the story planner's own pass 1 already uses
# (`editorial_story_shortlist.MIN_GAP_IN_CAPTURE_GROUP_SECONDS`): reused here so a day's
# capacity and the moments it later funds can never disagree about what is distinct.
MOMENT_SPACING_SECONDS = 300.0


def _when(row: Mapping[str, Any]) -> datetime | None:
    taken = row.get("taken")
    if isinstance(taken, datetime):
        return taken
    if isinstance(taken, str):
        try:
            return datetime.fromisoformat(taken)
        except ValueError:
            return None
    return None


def _window(row: Mapping[str, Any]) -> tuple[datetime, datetime] | None:
    when = _when(row)
    if when is None:
        return None
    return when, when + timedelta(seconds=float(row.get("seconds") or 0.0))


def _windows_overlap(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    window_a, window_b = _window(a), _window(b)
    if window_a is None or window_b is None:
        return False
    return window_a[0] < window_b[1] and window_b[0] < window_a[1]


def is_new_shot(candidate: Mapping[str, Any], kept: Sequence[Mapping[str, Any]]) -> bool:
    """Whether `candidate` is its own shot against every kept shot of the same capture
    context: a ``kind == "video"`` counts once its window clears every kept video's
    window; anything else counts once it is five real minutes from every kept shot's own
    time. A candidate with no readable time is always kept -- there is nothing to compare
    it against.
    """
    if candidate.get("kind") == "video":
        return not any(k.get("kind") == "video" and _windows_overlap(candidate, k) for k in kept)
    when = _when(candidate)
    if when is None:
        return True
    return all(
        (other := _when(k)) is None or abs((when - other).total_seconds()) >= MOMENT_SPACING_SECONDS
        for k in kept
    )


def distinct_shots(shots: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """`shots`, earliest first, kept only once each clears `is_new_shot` against what the
    walk has kept so far. The filter is stateful (each decision reads every earlier one),
    so this is not a plain comprehension's independent per-item test."""
    kept: list[Mapping[str, Any]] = []
    for shot in sorted(shots, key=lambda s: _when(s) or datetime.min):
        kept.extend([shot] if is_new_shot(shot, kept) else [])
    return kept
