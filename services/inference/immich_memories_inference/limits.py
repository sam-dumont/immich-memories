"""How much one request may make the service hold, decided before its body is read.

FastAPI parses a JSON or multipart body in full before a route sees it, so a cap in
the route is too late: the bytes are already in memory or spooled to disk. This
middleware refuses an announced oversize body unread, cuts off one that turns out
larger than announced (or announced nothing), and takes a seat for the route before
the first byte, so a busy route says 429 instead of queueing bodies.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Room for the multipart or JSON envelope around the payload a route caps itself.
ENVELOPE_BYTES = 1024 * 1024
RETRY_AFTER_SECONDS = 5


@dataclass(frozen=True)
class RouteLimit:
    """The most bytes a POST to the route may send, and how many may be read at once."""

    max_body_bytes: int
    seats: int


class BodyTooLarge(Exception):
    """The body went past its route's cap while it was being read."""


class BoundedBodies:
    """ASGI middleware applying a `RouteLimit` to each POST path it names."""

    def __init__(self, app: ASGIApp, limits: Mapping[str, RouteLimit]) -> None:
        self.app = app
        self._limits = dict(limits)
        self._seats = {path: asyncio.Semaphore(limit.seats) for path, limit in limits.items()}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        limit = self._limits.get(scope["path"]) if scope["type"] == "http" else None
        if limit is None or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return
        declared = _content_length(scope)
        if declared is not None and declared > limit.max_body_bytes:
            await _refuse(send, 413, f"request body is larger than {limit.max_body_bytes} bytes")
            return
        seat = self._seats[scope["path"]]
        # No await between the check and the acquire, so no other request takes the seat.
        if seat.locked():
            await _refuse(send, 429, "busy; retry shortly", retry_after=RETRY_AFTER_SECONDS)
            return
        async with seat:
            await _capped(self.app, limit.max_body_bytes, scope, receive, send)


async def _capped(app: ASGIApp, ceiling: int, scope: Scope, receive: Receive, send: Send) -> None:
    received = 0
    exceeded = False
    started = False

    async def counted() -> Message:
        nonlocal received, exceeded
        message = await receive()
        if message["type"] == "http.request":
            received += len(message.get("body", b""))
            if received > ceiling:
                exceeded = True
                raise BodyTooLarge
        return message

    async def guarded(message: Message) -> None:
        nonlocal started
        # The route answers a broken body with its own 400; the client is owed the 413.
        if exceeded:
            return
        started = True
        await send(message)

    try:
        await app(scope, counted, guarded)
    except BodyTooLarge:
        pass
    if exceeded and not started:
        await _refuse(send, 413, f"request body is larger than {ceiling} bytes")


def _content_length(scope: Scope) -> int | None:
    for name, value in scope["headers"]:
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


async def _refuse(send: Send, status: int, detail: str, *, retry_after: int | None = None) -> None:
    body = json.dumps({"detail": detail}).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    if retry_after is not None:
        headers.append((b"retry-after", str(retry_after).encode()))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})
