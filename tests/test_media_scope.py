"""Which configured account may answer a media request for one id (pre-cache check)."""

from __future__ import annotations

import pytest

from immich_memories.api.immich import ImmichNotFoundError
from immich_memories.config_models import ImmichConfig, ImmichConnection
from immich_memories.web.media_scope import account_for_asset, account_for_person, connection_for


class _FakeImmich:
    """Each account only reads the id it owns; everything else is a 404."""

    calls: list[tuple[str, str]] = []
    owners: dict[str, str] = {}

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

    def get_person(self, person_id: str):
        self._own_or_404(person_id)


@pytest.fixture(autouse=True)
def fake_immich(monkeypatch):
    _FakeImmich.calls = []
    _FakeImmich.owners = {}
    monkeypatch.setattr("immich_memories.api.sync_client.SyncImmichClient", _FakeImmich)
    return _FakeImmich


@pytest.fixture
def single_account() -> ImmichConfig:
    return ImmichConfig(url="http://primary.test", api_key="primary-key")


@pytest.fixture
def two_accounts() -> ImmichConfig:
    return ImmichConfig(
        url="http://primary.test",
        api_key="primary-key",
        accounts={"partner": ImmichConnection(url="http://partner.test", api_key="partner-key")},
    )


def test_connection_for_the_primary_is_the_config_itself(two_accounts):
    assert connection_for(two_accounts, "primary") is two_accounts


def test_connection_for_a_named_account_is_its_own_connection(two_accounts):
    assert connection_for(two_accounts, "partner").api_key == "partner-key"


def test_single_account_never_probes_immich(single_account):
    assert account_for_asset(single_account, "whatever") == "primary"
    assert _FakeImmich.calls == []


def test_a_primary_owned_asset_resolves_to_primary(two_accounts):
    _FakeImmich.owners["asset-1"] = "primary-key"

    assert account_for_asset(two_accounts, "asset-1") == "primary"
    assert _FakeImmich.calls == [("primary-key", "asset-1")], "the partner is never asked"


def test_a_partner_owned_asset_resolves_to_partner_after_the_primary_refuses(two_accounts):
    _FakeImmich.owners["asset-2"] = "partner-key"

    assert account_for_asset(two_accounts, "asset-2") == "partner"
    assert _FakeImmich.calls == [("primary-key", "asset-2"), ("partner-key", "asset-2")]


def test_an_asset_no_configured_account_owns_resolves_to_none(two_accounts):
    assert account_for_asset(two_accounts, "asset-3") is None
    assert _FakeImmich.calls == [("primary-key", "asset-3"), ("partner-key", "asset-3")]


def test_the_probe_result_is_kept_for_the_process_not_repeated(two_accounts):
    _FakeImmich.owners["asset-4"] = "partner-key"

    assert account_for_asset(two_accounts, "asset-4") == "partner"
    first_round = list(_FakeImmich.calls)
    assert account_for_asset(two_accounts, "asset-4") == "partner"

    assert _FakeImmich.calls == first_round, "a second request for the same id made no new call"


def test_a_person_resolves_the_same_way_as_an_asset(two_accounts):
    _FakeImmich.owners["person-1"] = "partner-key"

    assert account_for_person(two_accounts, "person-1") == "partner"
    assert _FakeImmich.calls == [("primary-key", "person-1"), ("partner-key", "person-1")]
