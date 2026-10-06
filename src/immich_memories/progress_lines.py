"""Which counted progress lines a plain log keeps, when no terminal redraws them in place.

A terminal redraws one line per stage; a cron job, a log file or the pasted run report gets
every update as a new line. A stage's start, each quarter and its end tell the same story in
five lines instead of one per picture (#2161).
"""

from __future__ import annotations

import re

_COUNTED = re.compile(r"^(?P<stage>.+?):\s+(?P<done>[\d,]+)/(?P<total>[\d,]+)\b")
_MARKS = 4


class StageLines:
    """Remembers how far each counted stage has been reported."""

    def __init__(self) -> None:
        self._reported: dict[str, tuple[int, int]] = {}

    def keeps(self, stage: str, done: int, total: int) -> bool:
        """Whether `done` of `total` reaches a mark this stage has not logged yet.

        A count that goes back down is a new pass of the stage, and starts over.
        """
        if total <= 0:
            return True
        mark = min(_MARKS, max(0, done) * _MARKS // total)
        last = self._reported.get(stage)
        if last is not None and done >= last[1] and mark <= last[0]:
            return False
        self._reported[stage] = (mark, done)
        return True

    def keeps_line(self, text: str) -> bool:
        """`keeps` for a line shaped "<stage>: <done>/<total> ..."; any other line is kept."""
        counted = _COUNTED.match(text)
        if counted is None:
            return True
        return self.keeps(
            counted["stage"],
            int(counted["done"].replace(",", "")),
            int(counted["total"].replace(",", "")),
        )
