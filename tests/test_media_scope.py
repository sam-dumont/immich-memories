"""Which configured account may answer a media request for one id (pre-cache check)."""

from __future__ import annotations

import pytest

from immich_memories.api.immich import ImmichNotFoundError
from immich_memories.config_models import ImmichConfig, ImmichConnection
from immich_memories.web.media_scope import account_for_asset, account_for_person, connection_for


class _FakeImmich:
    """Each account only reads the id it owns; everything else is a 404, unless that
    (account, id) pair is listed as unreachable, where it raises a connection error."""

    calls: list[tuple[str, str]] = []
    owners: dict[str, str] = {}
    unreachable: set[tuple[str, str]] = set()

    def __init__(self, *, base_url: str, api_key: str) -> None:
        self._api_key = api_key

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def _own_or_404(self, item_id: str) -> None:
        _FakeImmich.calls.append((self._api_key, item_id))
        if (self._api_key, item_id) in _FakeImmich.unreachable:
            raise ConnectionError("the server did not answer")
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
    _FakeImmich.unreachable = set()
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


def test_a_timeout_from_every_account_is_never_cached_as_a_404(two_accounts):
    _FakeImmich.unreachable |= {("primary-key", "asset-flaky"), ("partner-key", "asset-flaky")}

    assert account_for_asset(two_accounts, "asset-flaky") is None
    first_round = list(_FakeImmich.calls)
    assert account_for_asset(two_accounts, "asset-flaky") is None

    assert len(_FakeImmich.calls) == 2 * len(first_round), (
        "an outage answer is never trusted: the next request probes again"
    )


def test_a_mix_of_refusal_and_outage_is_never_cached(two_accounts):
    # The primary cleanly says no (not in `owners`, not unreachable); only the partner's
    # own account is down. Nobody has confirmed "no" on the partner's behalf, so the
    # answer must not freeze into a 404.
    _FakeImmich.unreachable.add(("partner-key", "asset-mixed"))
    account_for_asset(two_accounts, "asset-mixed")
    first_round = list(_FakeImmich.calls)

    assert account_for_asset(two_accounts, "asset-mixed") is None
    assert len(_FakeImmich.calls) == 2 * len(first_round)


def test_a_config_reload_never_reuses_a_stale_answer(two_accounts):
    _FakeImmich.owners["asset-5"] = "partner-key"
    assert account_for_asset(two_accounts, "asset-5") == "partner"

    reloaded = ImmichConfig(
        url="http://primary.test",
        api_key="primary-key",
        accounts={"partner": ImmichConnection(url="http://partner.test", api_key="rekeyed")},
    )
    _FakeImmich.calls = []

    assert account_for_asset(reloaded, "asset-5") is None, "the rekeyed partner owns nothing yet"
    assert _FakeImmich.calls == [("primary-key", "asset-5"), ("rekeyed", "asset-5")], (
        "the reload's own accounts were asked fresh, not answered from the old config's cache"
    )


def test_a_removed_account_never_raises_for_an_id_the_old_config_cached(two_accounts):
    _FakeImmich.owners["asset-6"] = "partner-key"
    assert account_for_asset(two_accounts, "asset-6") == "partner"

    without_partner = ImmichConfig(
        url="http://primary.test",
        api_key="primary-key",
        accounts={"cousin": ImmichConnection(url="http://cousin.test", api_key="cousin-key")},
    )

    # Must resolve against `without_partner`'s own accounts, never hand back "partner"
    # (which would make `connection_for` raise `KeyError` against this config).
    assert account_for_asset(without_partner, "asset-6") is None


def test_the_cache_is_capped_and_evicts_the_oldest_entry(monkeypatch, two_accounts):
    import immich_memories.web.media_scope as media_scope

    monkeypatch.setattr(media_scope, "_MAX_ENTRIES", 2)
    for asset_id in ("asset-a", "asset-b", "asset-c"):
        _FakeImmich.owners[asset_id] = "primary-key"
        account_for_asset(two_accounts, asset_id)

    _FakeImmich.calls = []
    account_for_asset(two_accounts, "asset-a")

    assert _FakeImmich.calls == [("primary-key", "asset-a")], (
        "the first id was evicted once a third was cached, so it is probed again"
    )
