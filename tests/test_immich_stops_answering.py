"""A server that keeps refusing stops the run early, with one message, not ten minutes of retries."""

from __future__ import annotations

import httpx
import pytest

from immich_memories.api.immich import (
    UNREACHABLE_AFTER_REQUESTS,
    ImmichAPIError,
    ImmichClient,
    ImmichStoppedAnswering,
)


def _client_refusing_after(answered: int) -> tuple[ImmichClient, list[int]]:
    sent: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(1)
        if len(sent) > answered:
            raise httpx.ConnectError("Connection refused", request=request)
        return httpx.Response(200, json={"major": 2, "minor": 0, "patch": 0})

    client = ImmichClient("http://immich.internal:2283", "secret-key")
    client._client = httpx.AsyncClient(
        base_url=client.base_url, transport=httpx.MockTransport(handler)
    )
    return client, sent


async def test_a_server_that_starts_refusing_stops_the_run_after_a_few_failed_requests(
    monkeypatch,
):
    monkeypatch.setattr("immich_memories.api.immich._BACKOFF_BASE", 0.0)
    client, _sent = _client_refusing_after(answered=2)
    await client.get_server_info()
    await client.get_server_info()

    with pytest.raises(ImmichStoppedAnswering) as raised:
        for _ in range(UNREACHABLE_AFTER_REQUESTS + 5):
            try:
                await client.get_server_info()
            except ImmichStoppedAnswering:
                raise
            except Exception:  # noqa: BLE001 - the per-request failures a caller logs and skips
                continue

    message = str(raised.value)
    assert "immich.internal:2283 stopped answering" in message
    assert "rerun the same command to continue" in message
    assert "secret-key" not in message


async def test_once_stopped_no_further_request_is_sent(monkeypatch):
    monkeypatch.setattr("immich_memories.api.immich._BACKOFF_BASE", 0.0)
    client, sent = _client_refusing_after(answered=0)
    with pytest.raises(ImmichStoppedAnswering):
        for _ in range(UNREACHABLE_AFTER_REQUESTS):
            try:
                await client.get_server_info()
            except ImmichStoppedAnswering:
                raise
            except Exception:  # noqa: BLE001
                continue
    seen = len(sent)

    with pytest.raises(ImmichStoppedAnswering):
        await client.get_server_info()

    assert len(sent) == seen


async def test_one_flaky_request_between_good_ones_never_stops_the_run(monkeypatch):
    monkeypatch.setattr("immich_memories.api.immich._BACKOFF_BASE", 0.0)
    calls = iter([False, False, False, True] * 10)

    def handler(request: httpx.Request) -> httpx.Response:
        if next(calls):
            return httpx.Response(200, json={"major": 2, "minor": 0, "patch": 0})
        raise httpx.ConnectError("Connection refused", request=request)

    client = ImmichClient("http://immich.internal:2283", "k")
    client._client = httpx.AsyncClient(
        base_url=client.base_url, transport=httpx.MockTransport(handler)
    )
    for _ in range(8):
        try:
            await client.get_server_info()
        except ImmichStoppedAnswering:
            pytest.fail("a request that failed then recovered must reset the count")
        except Exception:  # noqa: BLE001
            continue


def test_the_cli_ends_the_run_with_the_one_message_and_no_traceback():
    from click.testing import CliRunner

    from immich_memories.cli import main

    @main.command("stopped-probe")
    def probe():
        raise ImmichStoppedAnswering(
            "Immich at h stopped answering; rerun the same command to continue"
        )

    try:
        result = CliRunner().invoke(main, ["stopped-probe"])
    finally:
        main.commands.pop("stopped-probe")

    assert result.exit_code == 1
    assert "Immich at h stopped answering" in result.output
    assert "Traceback" not in result.output


def _client_seeing_timeouts(refuse: bool) -> tuple[ImmichClient, list[float | None]]:
    connect_timeouts: list[float | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        connect_timeouts.append(request.extensions["timeout"]["connect"])
        if refuse:
            raise httpx.ConnectTimeout("", request=request)
        return httpx.Response(200, json={"major": 2, "minor": 0, "patch": 0})

    client = ImmichClient("http://immich.internal:2283", "secret-key", timeout=30.0)
    client._client = httpx.AsyncClient(
        base_url=client.base_url, transport=httpx.MockTransport(handler), timeout=30.0
    )
    return client, connect_timeouts


async def test_the_first_contact_gives_up_on_connecting_quickly_then_the_client_relaxes():
    client, connect_timeouts = _client_seeing_timeouts(refuse=False)

    await client.get_server_info()
    await client.get_server_info()

    assert connect_timeouts[0] <= 10
    assert connect_timeouts[1] == 30.0


async def test_an_immich_that_never_answered_ends_with_the_rerun_hint(monkeypatch):
    monkeypatch.setattr("immich_memories.api.immich._BACKOFF_BASE", 0.0)
    client, _ = _client_seeing_timeouts(refuse=True)

    with pytest.raises(ImmichAPIError) as raised:
        await client.get_server_info()

    assert "cannot reach immich.internal:2283" in str(raised.value)
    assert "rerun the same command" in str(raised.value)
