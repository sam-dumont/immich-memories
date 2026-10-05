"""The web client's pictures: thumbnails and face crops from the shared cache (#824).

Every picture is a URL the browser caches, decodes lazily and evicts, never an inlined data
URI; a miss is fetched from Immich once, server-side, so the API key stays on the server.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from immich_memories.cache.thumbnail_cache import ThumbnailCache
from immich_memories.cache.thumbnail_sizes import AVATAR_PX, GRID_THUMBNAIL_PX
from immich_memories.config_loader import Config
from immich_memories.web.auth import is_bypass_path
from immich_memories.web.dependencies import immich_face, immich_preview, thumbnail_cache
from tests.web_api_fixtures import api_client, config_in


def _jpeg(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (200, 120, 40)).save(buffer, "JPEG")
    return buffer.getvalue()


@pytest.fixture
def cache(tmp_path: Path) -> ThumbnailCache:
    store = ThumbnailCache(tmp_path / "thumbs")
    store.put("asset-1", "preview", _jpeg(1600, 900))
    return store


@pytest.fixture
def fetched() -> list[str]:
    return []


@pytest.fixture
def client(tmp_path: Path, cache: ThumbnailCache, fetched: list[str]) -> TestClient:
    faces = {"abc-123": _jpeg(600, 600)}

    def fetch_face(person_id: str, _account: str) -> bytes | None:
        fetched.append(person_id)
        return faces.get(person_id)

    client = api_client(config_in(tmp_path))
    client.app.dependency_overrides[thumbnail_cache] = lambda: cache
    # WHY: Immich is the external boundary; the unit tier has no Immich to read from.
    client.app.dependency_overrides[immich_preview] = lambda: lambda _asset_id, _account: None
    client.app.dependency_overrides[immich_face] = lambda: fetch_face
    return client


def test_a_cached_preview_is_served_as_a_small_thumbnail(client, cache):
    response = client.get("/api/v1/assets/asset-1/thumbnail")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert "private" in response.headers["cache-control"]
    with Image.open(io.BytesIO(response.content)) as image:
        assert max(image.size) <= GRID_THUMBNAIL_PX
    assert cache.get("asset-1", "thumbnail") is not None, (
        "the derived thumbnail is cached for the next request"
    )


def test_the_preview_size_is_served_verbatim(client, cache):
    response = client.get("/api/v1/assets/asset-1/thumbnail", params={"size": "preview"})

    assert response.status_code == 200
    assert response.content == cache.get("asset-1", "preview")


def test_an_asset_neither_cache_nor_immich_has_is_a_404(client):
    assert client.get("/api/v1/assets/asset-2/thumbnail").status_code == 404


def test_a_malformed_id_or_size_never_reaches_the_cache(client):
    assert client.get("/api/v1/assets/..%2F..%2Fetc%2Fpasswd/thumbnail").status_code == 404
    assert client.get("/api/v1/assets/asset-1/thumbnail?size=original").status_code != 200


def test_a_face_is_fetched_once_then_served_from_the_cache(client, fetched):
    first = client.get("/api/v1/people/abc-123/face")
    second = client.get("/api/v1/people/abc-123/face")

    assert first.status_code == 200 and second.status_code == 200
    assert first.headers["content-type"] == "image/jpeg"
    assert "private" in first.headers["cache-control"]
    assert fetched == ["abc-123"], "the second request must come from the cache"
    with Image.open(io.BytesIO(second.content)) as image:
        assert max(image.size) <= AVATAR_PX, "a face crop is served at avatar size"


def test_a_person_immich_does_not_know_is_a_404(client):
    assert client.get("/api/v1/people/nobody/face").status_code == 404


def test_a_manual_person_never_reaches_immich(client, fetched):
    assert client.get("/api/v1/people/manual:abc/face").status_code == 404
    assert fetched == []


@pytest.mark.parametrize(
    "path", ["/api/v1/assets/asset-1/thumbnail", "/api/v1/people/abc-123/face"]
)
def test_picture_routes_are_not_auth_bypass_paths(path):
    """The auth middleware gates every path it does not list; these must stay unlisted."""
    assert not is_bypass_path(path)


class _FakeAccountsImmich:
    """Two configured accounts, each only able to read the asset/person it owns."""

    calls: list[tuple[str, str]] = []  # (api_key, id) for every probe or fetch
    owners: dict[str, str] = {}  # id -> the api_key that owns it

    def __init__(self, *, base_url: str, api_key: str) -> None:
        self._api_key = api_key

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def _own_or_404(self, item_id: str) -> None:
        _FakeAccountsImmich.calls.append((self._api_key, item_id))
        if _FakeAccountsImmich.owners.get(item_id) != self._api_key:
            from immich_memories.api.immich import ImmichNotFoundError

            raise ImmichNotFoundError("not found", status_code=404)

    def get_asset(self, asset_id: str):
        self._own_or_404(asset_id)
        from types import SimpleNamespace

        return SimpleNamespace(is_edited=False)

    def get_person(self, person_id: str):
        self._own_or_404(person_id)

    def get_asset_thumbnail(
        self, asset_id: str, size: str = "preview", *, edited: bool = False
    ) -> bytes:
        self._own_or_404(asset_id)
        return f"{self._api_key}:{asset_id}".encode()

    def get_person_thumbnail(self, person_id: str) -> bytes:
        self._own_or_404(person_id)
        return _jpeg(200, 200)


@pytest.fixture
def accounts_config(tmp_path: Path) -> Config:
    from immich_memories.config_models import ImmichConnection

    config = config_in(tmp_path)
    config.immich.url = "http://primary.test"
    config.immich.api_key = "primary-key"
    config.immich.accounts = {
        "partner": ImmichConnection(url="http://partner.test", api_key="partner-key")
    }
    return config


@pytest.fixture
def accounts_client(monkeypatch, accounts_config: Config, cache: ThumbnailCache) -> TestClient:
    _FakeAccountsImmich.calls = []
    _FakeAccountsImmich.owners = {"asset-primary": "primary-key", "asset-partner": "partner-key"}
    # WHY: Immich is the external boundary; a fake stands in for both configured accounts.
    monkeypatch.setattr("immich_memories.api.sync_client.SyncImmichClient", _FakeAccountsImmich)
    client = api_client(accounts_config)
    client.app.dependency_overrides[thumbnail_cache] = lambda: cache
    return client


def test_an_asset_owned_by_the_primary_account_is_served(accounts_client):
    response = accounts_client.get(
        "/api/v1/assets/asset-primary/thumbnail", params={"size": "preview"}
    )

    assert response.status_code == 200
    assert response.content == b"primary-key:asset-primary"


def test_a_partner_owned_asset_is_fetched_with_the_partner_key(accounts_client):
    response = accounts_client.get(
        "/api/v1/assets/asset-partner/thumbnail", params={"size": "preview"}
    )

    assert response.status_code == 200
    assert response.content == b"partner-key:asset-partner"
    # The primary was tried first and refused it; the partner's own key read it.
    assert ("primary-key", "asset-partner") in _FakeAccountsImmich.calls
    assert ("partner-key", "asset-partner") in _FakeAccountsImmich.calls


def test_an_asset_outside_every_configured_account_is_a_404(accounts_client, cache):
    response = accounts_client.get("/api/v1/assets/asset-nobody/thumbnail")

    assert response.status_code == 404


def test_scope_is_checked_before_the_cache_even_when_already_cached(accounts_client, cache):
    # An id neither configured account can see, but a picture already sits under it in
    # the shared cache (e.g. left over from before the account lost access to it).
    cache.put("asset-stale", "preview", _jpeg(100, 100))

    response = accounts_client.get("/api/v1/assets/asset-stale/thumbnail")

    assert response.status_code == 404


def test_a_partner_owned_face_is_fetched_with_the_partner_key(accounts_client):
    _FakeAccountsImmich.owners["person-partner"] = "partner-key"

    response = accounts_client.get("/api/v1/people/person-partner/face")

    assert response.status_code == 200
    assert ("partner-key", "person-partner") in _FakeAccountsImmich.calls


def test_a_person_outside_every_configured_account_is_a_404(accounts_client):
    assert accounts_client.get("/api/v1/people/person-nobody/face").status_code == 404


class _FakeImmich:
    """Stands in for SyncImmichClient. WHY: Immich is the external boundary here."""

    calls: list[str] = []
    payload: bytes | None = b"jpeg-bytes"

    def __init__(self, *, base_url: str, api_key: str) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def get_person_thumbnail(self, person_id: str) -> bytes:
        _FakeImmich.calls.append(person_id)
        if self.payload is None:
            raise RuntimeError("no face for this person")
        return self.payload


def _face_fetcher(monkeypatch, url: str, api_key: str):
    monkeypatch.setattr("immich_memories.api.sync_client.SyncImmichClient", _FakeImmich)
    _FakeImmich.calls = []
    return immich_face(Config(immich={"url": url, "api_key": api_key}))


def test_a_configured_immich_hands_back_the_face(monkeypatch):
    fetch = _face_fetcher(monkeypatch, "http://immich.test", "key")
    _FakeImmich.payload = b"jpeg-bytes"

    assert fetch("abc", "primary") == b"jpeg-bytes"
    assert _FakeImmich.calls == ["abc"]


def test_a_person_without_a_face_is_none_not_an_error(monkeypatch):
    fetch = _face_fetcher(monkeypatch, "http://immich.test", "key")
    _FakeImmich.payload = None

    assert fetch("abc", "primary") is None


def test_an_unconfigured_immich_is_never_called(monkeypatch):
    fetch = _face_fetcher(monkeypatch, "", "")

    assert fetch("abc", "primary") is None
    assert _FakeImmich.calls == []


class _FakePreviewImmich:
    """Stands in for SyncImmichClient. WHY: Immich is the external boundary here."""

    is_edited = False
    thumbnail_calls: list[tuple[str, dict]] = []

    def __init__(self, *, base_url: str, api_key: str) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def get_asset(self, asset_id: str):
        from types import SimpleNamespace

        return SimpleNamespace(is_edited=self.is_edited)

    def get_asset_thumbnail(
        self, asset_id: str, size: str = "preview", *, edited: bool = False
    ) -> bytes:
        _FakePreviewImmich.thumbnail_calls.append((asset_id, {"edited": edited}))
        return b"jpeg-bytes"


def _preview_fetcher(monkeypatch):
    monkeypatch.setattr("immich_memories.api.sync_client.SyncImmichClient", _FakePreviewImmich)
    _FakePreviewImmich.thumbnail_calls = []
    return immich_preview(Config(immich={"url": "http://immich.test", "api_key": "key"}))


def test_an_edited_asset_preview_asks_for_the_edited_render(monkeypatch):
    """The reviewer sees what the film will render (#2114)."""
    fetch = _preview_fetcher(monkeypatch)
    _FakePreviewImmich.is_edited = True

    fetch("asset-1", "primary")

    assert _FakePreviewImmich.thumbnail_calls == [("asset-1", {"edited": True})]


def test_an_unedited_asset_preview_request_is_unchanged(monkeypatch):
    fetch = _preview_fetcher(monkeypatch)
    _FakePreviewImmich.is_edited = False

    fetch("asset-1", "primary")

    assert _FakePreviewImmich.thumbnail_calls == [("asset-1", {"edited": False})]
