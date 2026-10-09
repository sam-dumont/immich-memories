"""An Immich outage names the host and the failure, and shows its retries."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import httpx
import pytest

from immich_memories.api.immich import ImmichAPIError, ImmichClient


async def _client_that_times_out() -> ImmichClient:
    def handler(request: httpx.Request) -> httpx.Response:
        # WHY: a blocked-egress Immich raises a timeout whose message is empty.
        raise httpx.ConnectTimeout("", request=request)

    client = ImmichClient("http://immich.internal:2283", "secret-key")
    client._client = httpx.AsyncClient(
        base_url=client.base_url, transport=httpx.MockTransport(handler)
    )
    return client


async def test_outage_error_names_the_host_and_the_exception(monkeypatch):
    # WHY: wall-clock delays are external; the real retry and transport still run.
    monkeypatch.setattr("immich_memories.api.immich.asyncio.sleep", AsyncMock())
    client = await _client_that_times_out()

    with pytest.raises(ImmichAPIError) as raised:
        await client.get_server_info()

    message = str(raised.value)
    assert "immich.internal:2283" in message
    assert "ConnectTimeout" in message
    assert "secret-key" not in message


async def test_outage_prints_retry_progress(monkeypatch, caplog):
    # WHY: wall-clock delays are external; the real retry and transport still run.
    monkeypatch.setattr("immich_memories.api.immich.asyncio.sleep", AsyncMock())
    client = await _client_that_times_out()

    with caplog.at_level(logging.WARNING), pytest.raises(ImmichAPIError):
        await client.get_server_info()

    text = caplog.text
    assert "retrying (2/7)" in text
    assert "retrying (7/7)" in text
