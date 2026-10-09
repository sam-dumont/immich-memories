"""Counting how many assets hold a set of people, without fetching any."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from immich_memories.api.search_service import SearchService


class TestCountAssetsWithPeople:
    @pytest.mark.asyncio
    async def test_it_asks_for_a_count_rather_than_paging_the_assets(self):
        # WHY: the Immich HTTP API. The point of the endpoint is that a pair
        # costs one small answer instead of every asset both people are in.
        request = AsyncMock(return_value={"total": 42})

        total = await SearchService(request).count_assets_with_people(["p1", "p2"])

        assert total == 42
        request.assert_awaited_once_with(
            "POST", "/search/statistics", json={"personIds": ["p1", "p2"]}
        )

    @pytest.mark.asyncio
    async def test_an_answer_without_a_total_counts_as_nothing_shared(self):
        # WHY: the Immich HTTP API, standing in for a server whose statistics
        # response shape differs from the one this was written against.
        request = AsyncMock(return_value={})

        assert await SearchService(request).count_assets_with_people(["p1", "p2"]) == 0

    @pytest.mark.asyncio
    async def test_a_window_narrows_the_count_to_pictures_taken_in_it(self):
        # WHY: the Immich HTTP API; the request body is the contract under test.
        request = AsyncMock(return_value={"total": 7})

        total = await SearchService(request).count_assets_with_people(
            ["p1"],
            taken_after=datetime(2025, 1, 1),
            taken_before=datetime(2025, 12, 31, 23, 59, 59),
        )

        assert total == 7
        body = request.await_args.kwargs["json"]
        assert body["takenAfter"].startswith("2025-01-01T00:00:00")
        assert body["takenBefore"].startswith("2025-12-31T23:59:59")


@pytest.mark.asyncio
async def test_owned_counts_page_past_partner_pictures_and_deduplicate_ids():
    def asset(identity, owner):
        return {
            "id": identity,
            "ownerId": owner,
            "type": "IMAGE",
            "fileCreatedAt": "2030-04-01T12:00:00Z",
            "fileModifiedAt": "2030-04-01T12:00:00Z",
            "updatedAt": "2030-04-01T12:00:00Z",
        }

    # WHY: Immich's HTTP boundary; a partner-only first page must not end paging.
    request = AsyncMock(
        side_effect=[
            {"assets": {"items": [asset("partner-picture", "partner")], "nextPage": "2"}},
            {
                "assets": {
                    "items": [
                        asset("own-one", "owner"),
                        asset("own-two", "owner"),
                        asset("own-one", "owner"),
                    ],
                    "nextPage": None,
                }
            },
        ]
    )
    total = await SearchService(request).count_assets_with_people(
        ["shared-person"], taken_after=datetime(2030, 4, 1), owner_id="owner"
    )
    assert total == 2
    assert [call.kwargs["json"]["page"] for call in request.await_args_list] == [1, 2]
    assert all(call.args == ("POST", "/search/metadata") for call in request.await_args_list)
    assert all(
        call.kwargs["json"]["personIds"] == ["shared-person"] for call in request.await_args_list
    )
