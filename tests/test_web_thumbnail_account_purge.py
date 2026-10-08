"""Web thumbnails belong to the account set that fetched them, including late writes.

The fake Immich has one owner per id; other accounts receive a real not-found error.
The HTTP routes, permission scopes, image processing and disk cache stay real.
"""

from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import create_autospec

import pytest

from immich_memories.api.immich import ImmichNotFoundError
from immich_memories.config_models import ImmichConnection
from tests.web_server_fixtures import basic_auth_config, server_client, signed_session

_ASSET = "asset-partner-owned"
_PERSON = "person-partner-owned"


def _tiny_jpeg() -> bytes:
    """A real, decodable JPEG: the grid thumbnail is derived from the preview once."""
    from PIL import Image

    buffer = io.BytesIO()
    with Image.new("RGB", (64, 64), (18, 52, 86)) as image:
        image.save(buffer, "JPEG")
    return buffer.getvalue()


class _FakeImmich:
    calls: list[tuple[str, str]] = []
    owners: dict[str, str] = {}
    paused: tuple[Event, Event] | None = None

    def __init__(self, *, base_url: str, api_key: str) -> None:
        self._api_key = api_key

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def _own_or_404(self, item_id: str) -> None:
        _FakeImmich.calls.append((self._api_key, item_id))
        if _FakeImmich.owners.get(item_id) != self._api_key:
            raise ImmichNotFoundError("not found", status_code=404)

    def get_asset(self, asset_id: str):
        self._own_or_404(asset_id)
        return SimpleNamespace(is_edited=False)

    def get_person(self, person_id: str):
        self._own_or_404(person_id)

    def get_asset_thumbnail(self, asset_id: str, *, size: str = "thumbnail", edited: bool = False):
        self._own_or_404(asset_id)
        if self.paused:
            arrived, resume = self.paused
            arrived.set()
            assert resume.wait(10), "the old account request was released"
        return _tiny_jpeg()

    def get_person_thumbnail(self, person_id: str):
        self._own_or_404(person_id)
        if self.paused:
            arrived, resume = self.paused
            arrived.set()
            assert resume.wait(10), "the old account request was released"
        return _tiny_jpeg()


@pytest.fixture(autouse=True)
def fake_immich(monkeypatch):
    _FakeImmich.calls = []
    _FakeImmich.owners = {_ASSET: "partner-key", _PERSON: "partner-key"}
    from immich_memories.api.sync_client import SyncImmichClient

    def connect(*, base_url, api_key):
        fake = _FakeImmich(base_url=base_url, api_key=api_key)
        client = create_autospec(SyncImmichClient, instance=True, spec_set=True)
        client.__enter__.return_value = client
        for name in ("get_asset", "get_person", "get_asset_thumbnail", "get_person_thumbnail"):
            getattr(client, name).side_effect = getattr(fake, name)
        return client

    # WHY: replace Immich HTTP with ownership checks, retaining the real client's call contract.
    constructor = create_autospec(SyncImmichClient, side_effect=connect)
    monkeypatch.setattr("immich_memories.api.sync_client.SyncImmichClient", constructor)
    yield
    _FakeImmich.calls = []
    _FakeImmich.owners = {}
    _FakeImmich.paused = None


@pytest.fixture(autouse=True)
def _clean_scope_caches():
    from immich_memories.web import media_scope

    media_scope._asset_accounts.clear()
    media_scope._person_accounts.clear()
    yield
    media_scope._asset_accounts.clear()
    media_scope._person_accounts.clear()


@pytest.fixture
def client_with_partner(monkeypatch, tmp_path):
    """A signed-in client over one shared thumbnail cache at `tmp_path`."""
    config = basic_auth_config()
    config.cache.directory = str(tmp_path)
    config.immich.url = "https://primary.example"
    config.immich.api_key = "primary-key"
    config.immich.accounts = {
        "partner": ImmichConnection(url="https://partner.example", api_key="partner-key")
    }
    client = server_client(monkeypatch, config)
    client.cookies.set("session", signed_session(config))

    return config, client


def test_a_cached_picture_dies_with_the_account_that_put_it_there(client_with_partner):
    config, client = client_with_partner
    first = client.get(f"/api/v1/assets/{_ASSET}/thumbnail")
    assert first.status_code == 200, "the partner's own picture serves while it is configured"

    config.immich.accounts = {}

    again = client.get(f"/api/v1/assets/{_ASSET}/thumbnail")
    assert again.status_code == 404, (
        "the bytes fetched as the partner's must not survive the partner's removal"
    )


def test_a_cached_face_dies_with_the_account_that_put_it_there(client_with_partner):
    config, client = client_with_partner
    first = client.get(f"/api/v1/people/{_PERSON}/face")
    assert first.status_code == 200

    config.immich.accounts = {}

    again = client.get(f"/api/v1/people/{_PERSON}/face")
    assert again.status_code == 404


def test_the_cache_survives_an_unchanged_account_set(client_with_partner):
    config, client = client_with_partner
    assert client.get(f"/api/v1/assets/{_ASSET}/thumbnail").status_code == 200
    calls = len(_FakeImmich.calls)

    assert client.get(f"/api/v1/assets/{_ASSET}/thumbnail").status_code == 200
    assert len(_FakeImmich.calls) == calls, "an unchanged account set still uses its cache"


def test_a_rotated_key_empties_the_cache_too(client_with_partner):
    config, client = client_with_partner
    assert client.get(f"/api/v1/assets/{_ASSET}/thumbnail").status_code == 200

    config.immich.accounts["partner"] = ImmichConnection(
        url="https://partner.example", api_key="rotated-key"
    )

    assert client.get(f"/api/v1/assets/{_ASSET}/thumbnail").status_code == 404


@pytest.mark.parametrize("route", [f"assets/{_ASSET}/thumbnail", f"people/{_PERSON}/face"])
def test_a_late_fetch_cannot_repopulate_the_removed_accounts_cache(client_with_partner, route):
    config, client = client_with_partner
    arrived, resume = Event(), Event()
    _FakeImmich.paused = (arrived, resume)
    url = f"/api/v1/{route}"

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(client.get, url)
        try:
            assert arrived.wait(10), "the old account fetch reached Immich"
            config.immich.accounts = {}
            assert client.get(url).status_code == 404
        finally:
            resume.set()
        assert pending.result(timeout=10).status_code == 200

    assert client.get(url).status_code == 404, "late bytes stay with the removed account set"
