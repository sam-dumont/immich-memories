"""How long one film may keep a render worker busy, from the work it holds.

The app's wait and the worker's own deadline read the same budget, so neither gives up on a
long film the other is still rendering. A fixed hour failed every film over about six
minutes: a worker spends most of its time animating photos and encoding, both of which grow
with the cut.
"""

from __future__ import annotations

# A 4-CPU worker with an entry-level NVIDIA card animates a photo in 20 to 25 seconds,
# prepares a video source in about 6, and encodes 2.5 to 4 seconds per second of film. These
# allowances are two to three times that, so a slower or busier worker still finishes; a
# render that hangs is caught by the stall guard, not by this total.
_SECONDS_PER_CLIP = 60.0
_SECONDS_PER_FILM_SECOND = 10.0
# Twelve hours: past this, a film is better rendered on a bigger machine than waited for.
CEILING_SECONDS = 12 * 3600.0
# The worker reports progress at least once a source, title or encoded second. Twenty silent
# minutes is a stuck render, not a slow one.
STALL_SECONDS = 20 * 60.0


def render_budget_seconds(clip_count: int, content_seconds: float, *, floor: float) -> float:
    """The seconds a film of ``clip_count`` clips and ``content_seconds`` may take.

    Never less than ``floor``, the configured deadline, which a short film keeps; never more
    than twelve hours unless the configured deadline itself is longer.
    """
    work = _SECONDS_PER_CLIP * clip_count + _SECONDS_PER_FILM_SECOND * content_seconds
    return max(floor, min(CEILING_SECONDS, work))


class StallGuard:
    """Notice a running render whose reported progress has stopped changing.

    A queued job is waiting for the lane, not stuck, so it never counts as stalled.
    """

    def __init__(self, now: float):
        self._heard: object = None
        self._since = now

    def stalled(self, *, running: bool, progress: object, now: float) -> bool:
        """Whether ``progress`` (any comparable report) has not moved for `STALL_SECONDS`."""
        if progress != self._heard or not running:
            self._heard, self._since = progress, now
            return False
        return now - self._since >= STALL_SECONDS
