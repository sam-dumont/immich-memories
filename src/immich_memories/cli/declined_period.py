"""How a run ends when its period holds nothing to film: an answer, not a failure (#2209, #2222).

Automation reads the `NOTHING_WORTH_A_FILM` marker off the child's output and records one
skipped attempt with the reason, so the marker stays the first words of the line.
"""

from __future__ import annotations

import calendar
import sys
from typing import NoReturn

from immich_memories.cli._helpers import print_info
from immich_memories.operations.auto_output import NOTHING_WORTH_A_FILM
from immich_memories.timeperiod import DateRange


def period_name(date_range: DateRange) -> str:
    """How a person names the period: "2019", "February 2019", or the dates."""
    start, end = date_range.start, date_range.end
    if date_range.is_calendar_year:
        return str(start.year)
    last_day = calendar.monthrange(start.year, start.month)[1]
    if start.day == 1 and (end.year, end.month, end.day) == (start.year, start.month, last_day):
        return start.strftime("%B %Y")
    return date_range.description


def nothing_worth_a_film_message(date_range: DateRange, stats: dict) -> str:
    """The marker stays first so automation's substring match keeps working
    (automation/runner.py); a people condition that excluded the whole pool adds its own
    specific reason after it (#1954)."""
    message = f"{NOTHING_WORTH_A_FILM} in {period_name(date_range)}"
    reason = stats.get("no_selection_reason")
    return f"{message}: {reason}" if reason else message


def end_run_without_a_film() -> None:
    """Close the observed run as "stopped before a film", not as a completed one (#2209).

    A declined period made nothing: history, the cooldown and the last-completed-run
    read must not count it. Without an observed run there is nothing to close.
    """
    from immich_memories.tracking.run_observations import current_tracker

    tracker = current_tracker()
    if tracker is not None and tracker.current_run is not None:
        tracker.cancel_run()


def stop_for_empty_period(date_range: DateRange) -> NoReturn:
    """End a run whose period holds no pictures or videos at all, as a declined film (#2222).

    The fetch itself succeeded, so this is an answer and not a failure: automation reads the
    marker and skips the attempt with a reason instead of reporting a bare exit code.
    """
    print_info(
        f"{NOTHING_WORTH_A_FILM} in {period_name(date_range)}: no pictures or videos in this period",
        soft_wrap=True,
    )
    end_run_without_a_film()
    sys.exit(0)
