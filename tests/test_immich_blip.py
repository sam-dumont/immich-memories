"""A brief LAN outage does not discard reads; writes retain their existing retry budget."""

import asyncio

import httpx
import pytest

from immich_memories.api.immich import ImmichAPIError, ImmichClient


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["albums", "search", "statistics", "download"])
async def test_read_recovers_after_a_twelve_second_outage(monkeypatch, tmp_path, operation):
    delays = []
    requests = []

    async def sleep(delay):
        delays.append(delay)

    def handle(request):
        requests.append(request)
        if sum(delays) < 12:
            raise httpx.ConnectError("temporarily unavailable", request=request)
        if operation == "albums":
            return httpx.Response(200, json=[{"id": "album-one"}])
        if operation == "search":
            return httpx.Response(200, json={"assets": {"items": [], "nextPage": None}})
        if operation == "statistics":
            return httpx.Response(200, json={"total": 4})
        return httpx.Response(200, content=b"complete original")

    # WHY: advance the backoff clock without waiting through a real LAN outage.
    monkeypatch.setattr(asyncio, "sleep", sleep)
    # WHY: Immich's HTTP boundary fails until the simulated outage has cleared.
    async with (
        httpx.AsyncClient(
            base_url="http://immich.test", transport=httpx.MockTransport(handle)
        ) as http,
        ImmichClient("http://immich.test", "test-key") as client,
    ):
        client._client = http
        if operation == "albums":
            assert await client.get_albums() == [{"id": "album-one"}]
        elif operation == "search":
            assert (await client.search_metadata()).assets.items == []
        elif operation == "statistics":
            assert await client.search.count_assets_with_people(["person-one"]) == 4
        else:
            path = await client.download_asset("asset-one", tmp_path / "original.jpg")
            assert path.read_bytes() == b"complete original"

    assert delays == [1, 2, 4, 8]
    assert len(requests) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("write", "expected_delays"), [(False, [1, 2, 4, 8, 15, 15]), (True, [1, 2])]
)
async def test_persistent_outage_exhausts_the_read_or_write_budget(
    monkeypatch, write, expected_delays
):
    delays = []
    requests = []

    async def sleep(delay):
        delays.append(delay)

    def unavailable(request):
        requests.append(request)
        raise httpx.ConnectError("temporarily unavailable", request=request)

    # WHY: observe the requested retry intervals without sleeping.
    monkeypatch.setattr(asyncio, "sleep", sleep)
    # WHY: a real HTTP client talks to an Immich transport that remains unavailable.
    async with (
        httpx.AsyncClient(
            base_url="http://immich.test", transport=httpx.MockTransport(unavailable)
        ) as http,
        ImmichClient("http://immich.test", "test-key") as client,
    ):
        client._client = http
        with pytest.raises(
            ImmichAPIError,
            match="Immich has not answered yet, rerun the same command once it does",
        ):
            if write:
                await client.create_album("Test album")
            else:
                await client.get_albums()

    assert delays == expected_delays
    assert len(requests) == len(delays) + 1


@pytest.mark.asyncio
async def test_initial_permission_probe_fails_without_the_running_read_backoff(monkeypatch):
    delays = []
    requests = []

    async def sleep(delay):
        delays.append(delay)

    def unavailable(request):
        requests.append(request)
        raise httpx.ConnectTimeout("unreachable", request=request)

    # WHY: capture the retry budget without waiting through an unreachable network.
    monkeypatch.setattr(asyncio, "sleep", sleep)
    # WHY: the HTTP boundary times out while the real startup permission check runs.
    async with (
        httpx.AsyncClient(
            base_url="http://immich.test", transport=httpx.MockTransport(unavailable)
        ) as http,
        ImmichClient("http://immich.test", "test-key") as client,
    ):
        client._client = http
        with pytest.raises(ImmichAPIError, match="Immich has not answered yet"):
            await client.require_read_permissions()

    assert len(requests) == 1
    assert delays == []
    assert requests[0].extensions["timeout"]["connect"] == 5.0
