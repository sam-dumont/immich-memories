"""Immich's own duplicate groups, read for a forwarded copy's original (`forwarded_fallback`)."""

from __future__ import annotations

import httpx
import pytest

from immich_memories.api.immich import ImmichClient
from tests.immich_fakes import ImmichWire

ORIGINAL = "11111111-1111-4111-8111-111111111111"
COPY = "22222222-2222-4222-8222-222222222222"


@pytest.mark.asyncio
async def test_each_duplicate_group_comes_back_as_its_asset_ids():
    def serve(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/duplicates"
        group = {"duplicateId": "33333333-3333-4333-8333-333333333333"}
        return httpx.Response(200, json=[group | {"assets": [{"id": ORIGINAL}, {"id": COPY}]}])

    # WHY: Immich's duplicates endpoint, refusing what the real one refuses.
    wire = ImmichWire(serve)
    client = ImmichClient("https://immich.test", "key", api_version="v3")
    client._client = httpx.AsyncClient(base_url="https://immich.test", transport=wire.transport)
    async with client:
        groups = await client.get_duplicate_groups()
    wire.assert_clean()

    assert groups == [(ORIGINAL, COPY)]
