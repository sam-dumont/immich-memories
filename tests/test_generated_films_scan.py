"""Finding the films this app already made, with the documented minimum key (#2353).

Without `tag.read` the app reads each video's tags one asset at a time. That read used to
walk every video in the library on every scope build, and one failed read ended the cut.
The scope a cut builds runs over the real client and an in-process fake Immich over HTTP.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest

from immich_memories.analysis.sources.window_context import library_source_scope
from immich_memories.api.generated_asset_tags import GENERATED_MEMORY_TAG
from immich_memories.api.permissions import READ_PERMISSIONS
from immich_memories.api.sync_client import SyncImmichClient
from immich_memories.config.loader import Config
from immich_memories.db import open_store
from immich_memories.timeperiod import DateRange
from immich_memories.tracking.models import RunMetadata
from immich_memories.tracking.run_database import RunDatabase

URL = "https://immich.example.test"
KEY = "synthetic-" * 4
JUNE = DateRange(datetime(2025, 6, 1), datetime(2025, 6, 30, 23, 59, 59))
_DETAIL = re.compile(r"^/api/assets/([^/]+)$")


def _video(asset_id: str, taken: datetime) -> dict:
    return {
        "id": asset_id,
        "ownerId": "owner",
        "type": "VIDEO",
        "fileCreatedAt": taken.isoformat(),
        "fileModifiedAt": taken.isoformat(),
        "updatedAt": taken.isoformat(),
    }


class Library:
    """Videos with their tags, served as Immich does: search rows carry no tags."""

    def __init__(self) -> None:
        self.videos: dict[str, tuple[dict, tuple[str, ...]]] = {}
        self.refused: set[str] = set()
        self.details: list[str] = []

    def hold(self, asset_id: str, taken: datetime, *tags: str) -> None:
        self.videos[asset_id] = (_video(asset_id, taken), tags)

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/api-keys/me":
            return httpx.Response(200, json={"permissions": list(READ_PERMISSIONS)})
        if path == "/api/search/metadata":
            query = json.loads(request.content)
            assert type(query["page"]) is int and "tagIds" not in query
            after = _at(query.get("takenAfter"), datetime.min.replace(tzinfo=UTC))
            before = _at(query.get("takenBefore"), datetime.max.replace(tzinfo=UTC))
            rows = [
                row
                for row, _tags in self.videos.values()
                if query.get("type") in (None, row["type"])
                and after <= datetime.fromisoformat(row["fileCreatedAt"]) <= before
            ]
            return httpx.Response(200, json={"assets": {"items": rows, "nextPage": None}})
        if detail := _DETAIL.match(path):
            asset_id = detail.group(1)
            self.details.append(asset_id)
            if asset_id in self.refused:
                return httpx.Response(500, json={"message": "Synthetic failure"})
            row, tags = self.videos[asset_id]
            return httpx.Response(200, json=row | {"tags": [{"value": tag} for tag in tags]})
        return httpx.Response(404, json={"message": "Not found"})


def _at(value: str | None, default: datetime) -> datetime:
    if not value:
        return default
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@pytest.fixture
def library(monkeypatch) -> Library:
    server = Library()
    real_client = httpx.AsyncClient
    # WHY: the Immich HTTP boundary; every request goes to the in-process fake above.
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(server.handler), **kwargs),
    )
    # WHY: wall-clock backoff is external; the real retry loop still runs.
    monkeypatch.setattr("immich_memories.api.immich.asyncio.sleep", AsyncMock())
    return server


def _config(tmp_path) -> Config:
    return Config(
        immich={"url": URL, "api_key": KEY, "api_version": "v2"},
        cache={"directory": str(tmp_path / "cache")},
    )


def _scope(tmp_path):
    with SyncImmichClient(base_url=URL, api_key=KEY, api_version="v2") as client:
        return library_source_scope(client, _config(tmp_path), [JUNE])


@pytest.mark.feature("api.generated-film-scan")
def test_one_failed_detail_read_falls_back_to_the_upload_receipts(tmp_path, library):
    june = datetime(2025, 6, 10, 12, tzinfo=UTC)
    library.hold("tagged-film", june, GENERATED_MEMORY_TAG)
    library.hold("unreadable", june + timedelta(hours=1))
    library.refused.add("unreadable")
    RunDatabase(open_store(_config(tmp_path))).save_run(
        RunMetadata(
            run_id="earlier",
            created_at=june,
            status="completed",
            immich_asset_id="uploaded-film",
        )
    )

    scope = _scope(tmp_path)

    # Partial tag answers are refused whole, so the receipts answer alone.
    assert scope.generated_asset_ids == ("uploaded-film",)


@pytest.mark.feature("api.generated-film-scan")
def test_a_scope_reads_the_tags_of_its_own_windows_videos_only(tmp_path, library):
    library.hold("june-film", datetime(2025, 6, 10, 12, tzinfo=UTC), GENERATED_MEMORY_TAG)
    library.hold("june-clip", datetime(2025, 6, 11, 12, tzinfo=UTC))
    for day in range(40):
        library.hold(f"older-{day}", datetime(2019, 1, 1, tzinfo=UTC) + timedelta(days=day))

    scope = _scope(tmp_path)

    assert scope.generated_asset_ids == ("june-film",)
    assert sorted(library.details) == ["june-clip", "june-film"]
