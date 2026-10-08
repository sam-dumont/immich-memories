"""A browser leaving mid-request never starts work or produces a server traceback."""

from __future__ import annotations

import pytest
from starlette.requests import Request

from immich_memories.web.request_validation import validate_json_request


@pytest.mark.asyncio
async def test_a_disconnected_json_request_stops_before_the_route() -> None:
    messages = iter(
        [
            {"type": "http.request", "body": b'{"partial":', "more_body": True},
            {"type": "http.disconnect"},
        ]
    )

    async def receive():
        return next(messages)

    async def route(_request):
        pytest.fail("an incomplete request must never reach the route")

    request = Request(
        {"type": "http", "headers": [(b"content-type", b"application/json")]}, receive
    )
    response = await validate_json_request(request, route)
    assert response.status_code == 400
    assert not response.body
