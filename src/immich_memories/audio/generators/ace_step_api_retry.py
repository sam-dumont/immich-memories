"""Retry for ACE-Step API calls that fail for a moment, not for good.

The server stops answering for tens of seconds while it decodes audio, and drops idle
keep-alive sockets. A poll that lands then fails with ``ReadError`` or a proxy's 502, although
the take finishes right after. Transport errors and 5xx are transient and retried with a
growing delay for a bounded time; a 4xx, the task's own failure and the overall timeout are not.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TRANSIENT_WINDOW_SECONDS = 120.0
_FIRST_DELAY_SECONDS = 2.0
_MAX_DELAY_SECONDS = 15.0


def is_transient(exc: BaseException) -> bool:
    """Whether a failed call is worth repeating: a dropped connection or a server-side error."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


async def send_with_retry(
    send: Callable[[], Awaitable[Any]],
    what: str,
    *,
    window: float | None = None,
) -> Any:
    """Await ``send()`` and raise for status; repeat transient failures until the window ends.

    ``window`` defaults to ``TRANSIENT_WINDOW_SECONDS``. The last error is raised once it
    passes, so the caller's own failure handling (and its log) sees the real cause.
    """
    deadline = time.monotonic() + (TRANSIENT_WINDOW_SECONDS if window is None else window)
    delay = _FIRST_DELAY_SECONDS
    while True:
        try:
            response = await send()
            response.raise_for_status()
            return response
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            if not is_transient(exc) or time.monotonic() + delay > deadline:
                raise
            logger.warning(
                "ACE-Step %s hit %s; retrying in %.0f s", what, type(exc).__name__, delay
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, _MAX_DELAY_SECONDS)
