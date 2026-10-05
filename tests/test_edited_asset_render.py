"""An asset edited in Immich's own editor (crop, rotate, mirror) renders as the edit, not
the untouched original (#2114): `isEdited` reaches the film through `edited=true` on the
preview and original endpoints, never through a guess at the file's own bytes.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from PIL import Image

from immich_memories.analysis.editorial_preparation_previews import ensure_preview
from immich_memories.api.asset_service import AssetService
from immich_memories.api.models import Asset, AssetType
from immich_memories.config_models_render import PhotoConfig
from immich_memories.photos.photo_pipeline import render_single_photo
from tests.conftest import make_asset


def _asset(**overrides) -> Asset:
    defaults = {
        "id": "asset-1",
        "type": AssetType.IMAGE,
        "fileCreatedAt": "2026-01-01T00:00:00Z",
        "fileModifiedAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-01T00:00:00Z",
    }
    return Asset(**{**defaults, **overrides})


def test_is_edited_parses_from_the_wire_field():
    assert _asset(isEdited=True).is_edited is True


def test_is_edited_defaults_false_on_a_server_too_old_to_send_it():
    """isEdited shipped in Immich 2.5; a server below that answers without the field."""
    assert _asset().is_edited is False


async def _request_via(http_client: httpx.AsyncClient, method: str, endpoint: str, **kwargs):
    # WHY: a minimal stand-in for ImmichClient._request -- the real one adds retry and
    # error-translation machinery this test does not exercise.
    response = await http_client.request(method, f"/api{endpoint}", **kwargs)
    return response.content


@pytest.mark.asyncio
async def test_edited_thumbnail_request_asks_for_the_edited_render(tmp_path):
    captured: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, content=b"thumb-bytes")

    async with httpx.AsyncClient(
        base_url="https://immich.test", transport=httpx.MockTransport(respond)
    ) as http_client:
        request_fn = lambda *a, **kw: _request_via(http_client, *a, **kw)  # noqa: E731
        service = AssetService(request_fn, "https://immich.test", lambda: http_client)
        await service.get_asset_thumbnail("asset-1", size="preview", edited=True)

    assert captured[0].url.params["edited"] == "true"
    assert captured[0].url.params["size"] == "preview"


@pytest.mark.asyncio
async def test_unedited_thumbnail_request_is_unchanged(tmp_path):
    captured: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, content=b"thumb-bytes")

    async with httpx.AsyncClient(
        base_url="https://immich.test", transport=httpx.MockTransport(respond)
    ) as http_client:
        request_fn = lambda *a, **kw: _request_via(http_client, *a, **kw)  # noqa: E731
        service = AssetService(request_fn, "https://immich.test", lambda: http_client)
        await service.get_asset_thumbnail("asset-1", size="preview")

    assert "edited" not in captured[0].url.params
    assert captured[0].url.params["size"] == "preview"


@pytest.mark.asyncio
async def test_edited_download_asks_for_the_edited_render_and_skips_the_size_check(tmp_path):
    """The edited render's size is unrelated to fileSizeInByte -- an expected_size_bytes
    that matches the original must not fail a download of the edited bytes."""
    captured: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, content=b"edited-jpeg-bytes")

    async with httpx.AsyncClient(
        base_url="https://immich.test", transport=httpx.MockTransport(respond)
    ) as http_client:
        service = AssetService(None, "https://immich.test", lambda: http_client)
        path = await service.download_asset(
            "asset-1",
            tmp_path / "original",
            expected_size_bytes=999_999,  # the original's size, never the edited render's
            edited=True,
        )

    assert captured[0].url.params["edited"] == "true"
    assert path.read_bytes() == b"edited-jpeg-bytes"


@pytest.mark.asyncio
async def test_unedited_download_request_is_unchanged(tmp_path):
    captured: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, content=b"original-bytes")

    async with httpx.AsyncClient(
        base_url="https://immich.test", transport=httpx.MockTransport(respond)
    ) as http_client:
        service = AssetService(None, "https://immich.test", lambda: http_client)
        await service.download_asset("asset-1", tmp_path / "original")

    assert "edited" not in captured[0].url.params


def test_render_of_an_edited_photo_downloads_the_edited_render(tmp_path):
    """The film gets the edited render: `render_single_photo` asks for it explicitly
    rather than downloading whatever the original happens to be (#2114)."""
    calls: list[tuple[str, Path, dict]] = []

    def download_fn(asset_id: str, path: Path, **kwargs) -> None:
        calls.append((asset_id, path, kwargs))
        Image.new("RGB", (96, 64), "orange").save(path, "JPEG")

    work = tmp_path / "work"
    work.mkdir()
    asset = make_asset("photo-1", is_edited=True)
    render_single_photo(asset, PhotoConfig(duration=1.0), 96, 64, work, download_fn, fps=5)

    assert calls == [(asset.id, work / f"{asset.id}.MOV", {"edited": True})]


def test_render_of_an_unedited_photo_requests_the_plain_original(tmp_path):
    calls: list[tuple[str, Path, dict]] = []

    def download_fn(asset_id: str, path: Path, **kwargs) -> None:
        calls.append((asset_id, path, kwargs))
        Image.new("RGB", (96, 64), "orange").save(path, "JPEG")

    work = tmp_path / "work"
    work.mkdir()
    asset = make_asset("photo-2", is_edited=False)
    render_single_photo(asset, PhotoConfig(duration=1.0), 96, 64, work, download_fn, fps=5)

    assert calls == [(asset.id, work / f"{asset.id}.MOV", {})]


def _jpeg_bytes(color: str) -> bytes:
    import io

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buffer, "JPEG")
    return buffer.getvalue()


def test_a_cache_entry_made_before_the_edit_is_refetched(tmp_path):
    """A preview cached while the picture was still unedited must not be read back as
    good once isEdited is true: `ensure_preview(edited=True)` always refetches (#2114)."""
    path = tmp_path / "preview.jpg"
    path.write_bytes(_jpeg_bytes("orange"))  # the stale, unedited preview already on disk

    calls: list[str] = []

    def fetch_preview(asset_id: str) -> bytes:
        calls.append(asset_id)
        return _jpeg_bytes("blue")  # the edited render

    ensure_preview(path, "asset-1", fetch_preview, edited=True)

    assert calls == ["asset-1"]
    assert path.read_bytes() == _jpeg_bytes("blue")


def test_an_unedited_cache_hit_never_refetches(tmp_path):
    path = tmp_path / "preview.jpg"
    path.write_bytes(_jpeg_bytes("orange"))

    def fetch_preview(asset_id: str) -> bytes:
        raise AssertionError("must not fetch a good cache hit")

    ensure_preview(path, "asset-1", fetch_preview, edited=False)

    assert path.read_bytes() == _jpeg_bytes("orange")
