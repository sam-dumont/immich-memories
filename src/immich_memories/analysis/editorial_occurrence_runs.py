"""A film of several occurrences tells each one's days as its own stories (no model).

A holiday's years, on this day's years and a birthday's earlier birthdays are separate
occurrences of one date. The rules reader groups consecutive photographed days into stories;
in such a film a story never runs from one occurrence into the next. A holiday film once named
a story "Days at home, 15 August – 15 August": 15 August 2004 and 15 August 2022, because an
episode with no selectable picture carried no day and sorted beside another year's.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import pairwise
from typing import Any

from immich_memories.timeperiod import DateRange


def episode_day(source: Any, episode: Any) -> str:
    """The earliest day an episode's own pictures were taken (ISO); empty when it has none."""
    days = [
        source.assets[asset].local_taken_at.date().isoformat()
        for moment in episode.moments
        for asset in source.moment_asset_ids.get(moment, ())
        if asset in source.assets
    ]
    return min(days, default="")


def within_occurrences(
    runs: Sequence[list[str]], day_of: Mapping[str, str], ranges: Sequence[DateRange]
) -> list[list[str]]:
    """`runs` of episode keys, cut wherever they move from one occurrence window into the next.

    A day in two windows belongs to the one that starts last: a birthday's year begins on the
    day its earlier birthday's window ends. A film of one window, or none, is left as it is,
    and a window across New Year (31 December to 1 January) is one occurrence.
    """
    windows = sorted(ranges, key=lambda window: window.start)
    if len(windows) < 2:
        return [run.copy() for run in runs]

    def occurrence(key: str) -> int:
        day = day_of[key][:10]
        held = [
            index
            for index, window in enumerate(windows)
            if day and window.start.date().isoformat() <= day <= window.end.date().isoformat()
        ]
        return held[-1] if held else -1

    cut: list[list[str]] = []
    for run in runs:
        cut.append([run[0]])
        for previous, key in pairwise(run):
            if occurrence(previous) == occurrence(key):
                cut[-1].append(key)
            else:
                cut.append([key])
    return cut
