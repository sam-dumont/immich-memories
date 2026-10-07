"""The log lines of a pasted report: one line per progress stage, one per repeated message."""

from __future__ import annotations

import re
from collections import Counter

# `Preparing previews: 33/39 · ~1s left in this stage` and `Prepared 3/7 sources`.
_PROGRESS = re.compile(
    r"^(?P<stage>Preparing [\w ]+?|Prepared)(?P<colon>:)? (?P<done>\d+)/(?P<total>\d+)(?P<rest>\b.*)?$"
)


def _progress_key(line: str) -> tuple[tuple[str, int], int] | None:
    found = _PROGRESS.match(line)
    if found is None:
        return None
    rest = (found["rest"] or "").split(" · ")[0]
    return (found["stage"] + rest, int(found["total"])), int(found["done"])


def _last_counts(lines: list[str]) -> dict[tuple[str, int], tuple[int, str]]:
    """Each counted stage's furthest line."""
    last: dict[tuple[str, int], tuple[int, str]] = {}
    for line in lines:
        if (progress := _progress_key(line)) is not None:
            key, done = progress
            if key not in last or done >= last[key][0]:
                last[key] = (done, line)
    return last


def collapse_log(lines: list[str]) -> list[str]:
    """Shorten a run's log for pasting, without touching the full log kept in the bundle.

    A counted stage keeps its last count where it first spoke, and a message that repeats
    (the burst de-duplication line is logged once per pass) shows once with how many times.
    """
    last = _last_counts(lines)
    repeats = Counter(line for line in lines if _progress_key(line) is None)
    shown: list[str] = []
    seen: set[object] = set()
    for line in lines:
        progress = _progress_key(line)
        identity = progress[0] if progress is not None else line
        if identity in seen:
            continue
        seen.add(identity)
        if progress is not None:
            shown.append(last[progress[0]][1])
        else:
            shown.append(f"{line} (x{repeats[line]})" if repeats[line] > 1 else line)
    return shown
