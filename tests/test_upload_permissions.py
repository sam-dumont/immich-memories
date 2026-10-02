"""Scoped upload keys degrade delivery without failing a completed film."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from immich_memories.api.album_service import AlbumService
from immich_memories.api.compatibility import ResolvedApiVersion
from immich_memories.api.permissions import UPLOAD_PERMISSIONS, ApiKeyCapabilities


def _scoped_key(*permissions: str) -> ApiKeyCapabilities:
    return ApiKeyCapabilities(frozenset(permissions))


@pytest.mark.asyncio
async def test_missing_upload_scope_keeps_local_film_without_writing_immich(tmp_path: Path):
    film = tmp_path / "film.mp4"
    film.write_bytes(b"completed film")
    request = AsyncMock()
    service = AlbumService(
        request,
        AsyncMock(return_value=ResolvedApiVersion.V3),
        AsyncMock(return_value=_scoped_key()),
    )

    result = await service.upload_memory(film, "Memories")

    assert result["asset_id"] is None
    assert result["delivery_complete"] is False
    assert result["missing_permissions"] == list(UPLOAD_PERMISSIONS)
    assert "asset.upload" in result["warnings"][0]
    assert film.read_bytes() == b"completed film"
    request.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_only_key_uploads_without_tags_album_or_previous_deletion(tmp_path: Path):
    film = tmp_path / "film.mp4"
    film.write_bytes(b"completed film")
    calls = []

    async def request(method, path, **kwargs):
        calls.append((method, path))
        if (method, path) == ("POST", "/assets"):
            return {"id": "new-film"}
        if (method, path) == ("GET", "/albums"):
            return []
        pytest.fail(f"Unexpected write: {method} {path}")

    service = AlbumService(
        request,
        AsyncMock(return_value=ResolvedApiVersion.V3),
        AsyncMock(return_value=_scoped_key("asset.upload")),
    )
    result = await service.upload_memory(film, "Memories")

    assert result["asset_id"] == "new-film"
    assert result["delivery_complete"] is False
    assert set(result["missing_permissions"]) == {
        "tag.create",
        "tag.asset",
        "album.create",
        "albumAsset.create",
    }
    assert "previous version kept: the key lacks asset.delete" in result["warnings"]
    assert calls == [("POST", "/assets"), ("GET", "/albums")]


@pytest.mark.asyncio
@pytest.mark.parametrize("album_name", ["Memories", None])
async def test_missing_album_scope_keeps_film_even_when_no_album_creation_needed(
    tmp_path: Path, album_name
):
    film = tmp_path / "film.mp4"
    film.write_bytes(b"completed film")
    calls = []

    async def request(method, path, **kwargs):
        calls.append((method, path))
        responses = {
            ("POST", "/assets"): {"id": "new-film"},
            ("GET", "/assets/new-film"): {
                "exifInfo": {"modifyDate": "2024-06-01"},
                "tags": [{"value": "immich-memories/generated"}],
            },
            ("PUT", "/tags"): [{"id": "provenance", "value": "immich-memories/generated"}],
            ("PUT", "/tags/provenance/assets"): [],
            ("GET", "/albums"): [{"id": "existing", "albumName": "Memories"}],
            ("PUT", "/albums/existing/assets"): [],
        }
        if (method, path) not in responses:
            pytest.fail(f"Unexpected request: {method} {path}")
        return responses[(method, path)]

    service = AlbumService(
        request,
        AsyncMock(return_value=ResolvedApiVersion.V3),
        AsyncMock(
            return_value=_scoped_key("asset.upload", "tag.create", "tag.asset", "albumAsset.create")
        ),
    )
    result = await service.upload_memory(film, album_name)

    assert result["delivery_complete"] is False
    assert result["album_id"] == ("existing" if album_name else None)
    assert result["missing_permissions"] == ["album.create"]
    assert any("album.create" in warning for warning in result["warnings"])
    assert "previous version kept: the key lacks asset.delete" in result["warnings"]
    assert (("PUT", "/albums/existing/assets") in calls) is bool(album_name)
    assert not any(method == "DELETE" for method, _ in calls)


@pytest.mark.asyncio
async def test_incomplete_provenance_keeps_previous_upload_even_with_delete_scope(tmp_path):
    film = tmp_path / "film.mp4"
    film.write_bytes(b"completed film")
    calls = []

    async def request(method, path, **kwargs):
        calls.append((method, path))
        responses = {
            ("POST", "/assets"): {"id": "new-film"},
            ("GET", "/albums"): [{"id": "existing", "albumName": "Memories"}],
            ("PUT", "/albums/existing/assets"): [],
        }
        if (method, path) not in responses:
            pytest.fail(
                f"Incomplete replacement must not inspect or delete old upload: {method} {path}"
            )
        return responses[(method, path)]

    service = AlbumService(
        request,
        AsyncMock(return_value=ResolvedApiVersion.V3),
        AsyncMock(return_value=_scoped_key("asset.upload", "albumAsset.create", "asset.delete")),
    )
    result = await service.upload_memory(film, "Memories")
    assert result["delivery_complete"] is False
    assert "previous version kept: delivery incomplete" in result["warnings"]
