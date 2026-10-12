"""A source preparation that settled for less than it set out to make says so (#2032).

A run takes a fallback so a film still comes out: the Live companion video when a
burst cannot merge, the components that did download, timestamp trims when the
audio cannot align them, software when the hardware encoder fails, SDR when a gain
map cannot be read. That is right for this film. Banked, the same lesser result
would go into every later film of the selection, long after the transient failure
behind it has passed.

Code that takes a fallback calls `note_fallback` where it decides to. The bank's
caller watches one preparation with `watching_fallbacks` and banks nothing that
noted one. The watch is per thread (a context variable), so preparations running
side by side on source workers never mark each other.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_noted: ContextVar[list[str] | None] = ContextVar("preparation_fallbacks", default=None)


def note_fallback(reason: str) -> None:
    """Record that the preparation under way used a fallback in place of its intended result."""
    reasons = _noted.get()
    if reasons is not None:
        reasons.append(reason)


@contextmanager
def watching_fallbacks() -> Iterator[list[str]]:
    """Collect the fallbacks one preparation takes, on this thread."""
    reasons: list[str] = []
    token = _noted.set(reasons)
    try:
        yield reasons
    finally:
        _noted.reset(token)
