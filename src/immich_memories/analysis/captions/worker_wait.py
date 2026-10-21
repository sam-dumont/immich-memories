"""Wait for a busy inference worker instead of failing the pictures it could not take.

The bundled worker serves one GPU phase at a time. While a render or a music phase holds the
GPU it answers 503, and a second run sharing the worker (an automatic run next to a manual one)
meets that for as long as the other job lasts. That is the worker being busy, not the picture
being bad, so the request is repeated with a growing delay until the bound runs out.
"""

from __future__ import annotations

import http.client
import logging
import time
import urllib.error
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

# WHY 25 minutes: a film render holding the worker's GPU takes up to about twenty minutes, so
# the wait has to outlast one. A worker busy for longer than that is stuck, not busy, and the
# run says so instead of waiting for ever.
WORKER_MAX_WAIT_SECONDS = 25 * 60.0
FIRST_DELAY_SECONDS = 2.0
MAX_DELAY_SECONDS = 30.0
# A Retry-After longer than this is a worker asking for a rest we would rather re-check.
MAX_RETRY_AFTER_SECONDS = 60.0
_REPORT_EVERY_SECONDS = 60.0
_RETRYABLE_STATUSES = frozenset({429, 503})

_sleep = time.sleep
_clock = time.monotonic

T = TypeVar("T")


class CaptionServerBusy(RuntimeError):
    """The caption worker is up but its GPU belongs to another phase right now."""


def _retry_after(exc: urllib.error.HTTPError) -> float | None:
    value = exc.headers.get("Retry-After") if exc.headers else None
    try:
        return max(0.0, min(float(value), MAX_RETRY_AFTER_SECONDS)) if value else None
    except ValueError:
        return None  # an HTTP-date form; the growing delay is close enough


def _is_reset(exc: BaseException) -> bool:
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    return isinstance(reason, ConnectionResetError | http.client.RemoteDisconnected)


def wait_while_busy(attempt: Callable[[], T]) -> T:
    """Run ``attempt``; repeat it while the worker answers 429/503 or drops the connection.

    Any other error, a 4xx included, goes straight to the caller: that is the picture's own
    answer. Past ``WORKER_MAX_WAIT_SECONDS`` it raises ``CaptionServerBusy``.
    """
    started = _clock()
    delay = FIRST_DELAY_SECONDS
    reported = started - _REPORT_EVERY_SECONDS
    while True:
        try:
            return attempt()
        except urllib.error.HTTPError as exc:
            if exc.code not in _RETRYABLE_STATUSES:
                raise
            asked = _retry_after(exc)
            cause: BaseException = exc
            exc.close()
        except (urllib.error.URLError, ConnectionError) as exc:
            if not _is_reset(exc):
                raise
            asked, cause = None, exc
        pause = asked if asked is not None else delay
        waited = _clock() - started
        if waited + pause > WORKER_MAX_WAIT_SECONDS:
            raise CaptionServerBusy(
                f"the inference worker stayed busy for {waited / 60:.0f} minutes "
                "(another job holds its GPU); rerun once it is free"
            ) from cause
        if _clock() - reported >= _REPORT_EVERY_SECONDS:
            reported = _clock()
            logger.warning(
                "Waiting for the inference worker (busy with another job, %.0f s so far)", waited
            )
        _sleep(pause)
        delay = min(delay * 2, MAX_DELAY_SECONDS)
