"""What the Immich client makes of answers a real server or its proxy can give (#2354).

Each test runs the real client against an in-process fake Immich over HTTP.
"""

from __future__ import annotations

import json

import httpx
import pytest
from click.testing import CliRunner

from immich_memories.api.immich import ImmichAPIError
from immich_memories.api.models import MetadataSearchResult
from immich_memories.api.sync_client import SyncImmichClient

URL = "https://immich.example.test"
KEY = "synthetic-" * 4
LOGIN_PAGE = "<html><body>Sign in to continue</body></html>"


def _client(handler) -> SyncImmichClient:
    client = SyncImmichClient(base_url=URL, api_key=KEY, api_version="v2")
    client._async_client._client = httpx.AsyncClient(
        base_url=URL, transport=httpx.MockTransport(handler)
    )
    return client


def _login_page(_request: httpx.Request) -> httpx.Response:
    # An SSO proxy in front of Immich answers an expired session with its own page.
    return httpx.Response(200, text=LOGIN_PAGE, headers={"content-type": "text/html"})


@pytest.mark.parametrize(
    "read",
    [
        lambda client: client.search_metadata(page=1, size=10),
        lambda client: client.get_asset("some-asset"),
        lambda client: client.get_time_buckets(),
    ],
    ids=["search", "asset", "timeline"],
)
def test_a_page_that_is_not_json_is_an_immich_error_naming_what_came_back(read):
    with _client(_login_page) as client, pytest.raises(ImmichAPIError) as raised:
        read(client)

    assert "not JSON" in str(raised.value)
    assert URL not in str(raised.value) and KEY not in str(raised.value)


def test_an_album_created_by_a_request_that_timed_out_is_not_created_twice(monkeypatch):
    from unittest.mock import AsyncMock

    albums: list[dict] = []
    posts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/albums":
            return httpx.Response(200, json=albums)
        if request.method == "POST" and request.url.path == "/api/albums":
            posts.append(json.loads(request.content)["albumName"])
            albums.append({"id": f"album-{len(albums) + 1}", "albumName": posts[-1]})
            if len(posts) == 1:
                # Immich stored the album; the answer never reached the client.
                raise httpx.ReadTimeout("timed out", request=request)
            return httpx.Response(201, json=albums[-1])
        return httpx.Response(404, json={"message": "Not found"})

    # WHY: wall-clock backoff is external; the real retry loop still runs.
    monkeypatch.setattr("immich_memories.api.immich.asyncio.sleep", AsyncMock())
    with _client(handler) as client:
        album_id = client.create_album("Summer 2025")
        resolved = client.resolve_album("Summer 2025")

    assert posts == ["Summer 2025"]
    assert album_id == resolved.id == "album-1"


@pytest.mark.parametrize("token", ["2", 2])
def test_a_search_page_names_its_next_page_as_a_number(token):
    page = MetadataSearchResult.model_validate({"assets": {"items": [], "nextPage": token}})

    assert page.next_page == 2


@pytest.mark.parametrize("token", [None, ""])
def test_a_last_search_page_names_no_next_page(token):
    page = MetadataSearchResult.model_validate({"assets": {"items": [], "nextPage": token}})

    assert page.next_page is None


def test_years_lists_every_year_holding_a_picture_or_a_video(tmp_path, monkeypatch):
    from immich_memories.cli import main

    asked: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/timeline/buckets":
            asked.append(dict(request.url.params))
            # Immich's timeline answers every asset; videos in 2022 and 2024, photos only
            # in 2021 and 2023.
            return httpx.Response(
                200,
                json=[
                    {"timeBucket": f"{year}-06-01T00:00:00.000Z", "count": 3}
                    for year in (2021, 2022, 2023, 2024)
                ],
            )
        if request.url.path == "/api/api-keys/me":
            return httpx.Response(200, json={"permissions": ["all"]})
        return httpx.Response(404, json={"message": "Not found"})

    real_client = httpx.AsyncClient
    # WHY: the Immich HTTP boundary; every request goes to the in-process fake above.
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    config = tmp_path / "config.yaml"
    config.write_text(f"immich:\n  url: {URL}\n  api_key: {KEY}\n  api_version: v2\n")

    result = CliRunner().invoke(main, ["-c", str(config), "years"])

    assert result.exit_code == 0, result.output
    assert "Years with pictures or videos:" in result.output
    listed = [line.strip("• ").strip() for line in result.output.splitlines() if "•" in line]
    assert listed == ["2024", "2023", "2022", "2021"]
    # One timeline call, with no media type the timeline would only ignore.
    assert len(asked) == 1 and "type" not in asked[0]
