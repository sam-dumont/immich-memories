"""Discovery reads every account `automation.accounts` selects (#1500 slice 10).

Two synthetic accounts, opened through a fake `open_accounts` at the Immich client
boundary (the same seam `api/accounts.py` itself already proves against real HTTP in
`test_immich_accounts.py`): this file is about what `CandidateDiscovery` does with what
each account returns, not about `open_accounts`'s own network behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pytest

from immich_memories.api.accounts import AccountUnavailable, OpenAccount
from immich_memories.api.compatibility import ResolvedApiVersion
from immich_memories.api.models import Person, TimeBucket, UserInfo
from immich_memories.automation import candidate_discovery as discovery_module
from immich_memories.automation.candidate_discovery import (
    CandidateDiscovery,
    ImmichDiscoveryError,
)
from immich_memories.config_loader import Config
from immich_memories.db import open_store
from immich_memories.people.companion import add_confirmed_person, bind_alias


@dataclass
class _FakeClient:
    """A minimal stand-in for `SyncImmichClient`, the boundary `open_accounts` opens."""

    buckets: list[TimeBucket]
    people: list[Person]
    counts: dict[str, int]
    closed: bool = field(default=False)
    fail: bool = False

    def get_time_buckets(self, **_kwargs):
        if self.fail:
            raise ConnectionError("account unreachable")
        return self.buckets

    def get_all_people(self, with_hidden: bool = False):
        return self.people

    def get_person_asset_count(self, person_id: str) -> int:
        return self.counts.get(person_id, 0)

    def close(self):
        self.closed = True


class _FakeRuns:
    def get_generated_memory_keys(self) -> set[str]:
        return set()

    def get_last_run_of_type(self, memory_type: str, source: str | None = None):
        return None


class _FakeAttempts:
    def consecutive_failures_by_key(self) -> dict:
        return {}


def _config(accounts: list[str]) -> Config:
    return Config(
        immich={
            "url": "https://primary.example.test",
            "api_key": "primary-key",
            "accounts": {
                "partner": {"url": "https://partner.example.test", "api_key": "partner-key"}
            },
        },
        automation={"accounts": accounts, "detect_trips": False},
    )


def _open_account(name: str, client: _FakeClient) -> OpenAccount:
    return OpenAccount(
        name=name,
        client=client,  # type: ignore[arg-type]
        user=UserInfo(id=f"user-{name}", email=f"{name}@example.test"),
        api_version=ResolvedApiVersion.V2,
    )


def _patch_open_accounts(monkeypatch, opened: dict[str, OpenAccount]):
    # WHY: the Immich client boundary; two synthetic accounts stand in for the real HTTP
    # opener already tested end to end in test_immich_accounts.py.
    monkeypatch.setattr(discovery_module, "open_accounts", lambda _immich, _names: opened)


def test_asset_counts_and_buckets_are_summed_across_selected_accounts(monkeypatch):
    primary = _FakeClient(
        buckets=[TimeBucket(count=10, timeBucket="2026-01-01")],
        people=[Person(id="kid-primary", name="Kid A", thumbnailPath="/t.jpg")],
        counts={"kid-primary": 30},
    )
    partner = _FakeClient(
        buckets=[TimeBucket(count=4, timeBucket="2026-01-01")],
        people=[Person(id="kid-partner", name="Kid A", thumbnailPath="/t.jpg")],
        counts={"kid-partner": 12},
    )
    opened = {
        "primary": _open_account("primary", primary),
        "partner": _open_account("partner", partner),
    }
    _patch_open_accounts(monkeypatch, opened)

    store = open_store(_config(["primary", "partner"]))
    person_id = add_confirmed_person(store, "Kid A", person_id="kid-primary")
    bind_alias(store, person_id, "kid-partner", account="partner")

    discovery = CandidateDiscovery(_config(["primary", "partner"]), _FakeRuns(), _FakeAttempts())
    snapshot = discovery._library_snapshot(discovery._config.automation, date(2026, 8, 1), store)

    assert snapshot.assets_by_month == {"2026-01": 14}
    assert snapshot.person_asset_counts == {"kid-primary": 42}
    assert len(snapshot.people) == 1
    assert primary.closed and partner.closed


def test_a_read_failure_on_any_selected_account_fails_discovery(monkeypatch):
    primary = _FakeClient(buckets=[], people=[], counts={})
    partner = _FakeClient(buckets=[], people=[], counts={}, fail=True)
    opened = {
        "primary": _open_account("primary", primary),
        "partner": _open_account("partner", partner),
    }
    _patch_open_accounts(monkeypatch, opened)

    config = _config(["primary", "partner"])
    store = open_store(config)
    discovery = CandidateDiscovery(config, _FakeRuns(), _FakeAttempts())

    with pytest.raises(ImmichDiscoveryError):
        discovery._library_snapshot(discovery._config.automation, date(2026, 8, 1), store)

    assert primary.closed and partner.closed


def test_an_unconfigured_selected_account_fails_before_any_account_is_read(monkeypatch):
    def _raise(_immich, _names):
        raise AccountUnavailable("Immich account 'partner' is not configured")

    monkeypatch.setattr(discovery_module, "open_accounts", _raise)
    config = _config(["primary", "partner"])
    store = open_store(config)
    discovery = CandidateDiscovery(config, _FakeRuns(), _FakeAttempts())

    with pytest.raises(ImmichDiscoveryError, match="not configured"):
        discovery._library_snapshot(discovery._config.automation, date(2026, 8, 1), store)


def test_default_accounts_reads_the_primary_alone(monkeypatch):
    primary = _FakeClient(
        buckets=[TimeBucket(count=5, timeBucket="2026-02-01")],
        people=[],
        counts={},
    )
    seen_names = {}

    def _open(_immich, names):
        seen_names["names"] = tuple(names)
        return {"primary": _open_account("primary", primary)}

    monkeypatch.setattr(discovery_module, "open_accounts", _open)
    config = _config([])
    store = open_store(config)
    discovery = CandidateDiscovery(config, _FakeRuns(), _FakeAttempts())

    snapshot = discovery._library_snapshot(discovery._config.automation, date(2026, 8, 1), store)

    assert seen_names["names"] == ("primary",)
    assert snapshot.assets_by_month == {"2026-02": 5}


def test_store_birth_date_overlays_the_immich_roster(monkeypatch):
    primary = _FakeClient(
        buckets=[],
        people=[Person(id="kid-a", name="Kid A", thumbnailPath="/t.jpg", birthDate="2018-01-01")],
        counts={"kid-a": 1},
    )
    _patch_open_accounts(monkeypatch, {"primary": _open_account("primary", primary)})

    config = _config([])
    store = open_store(config)
    add_confirmed_person(store, "Kid A", person_id="kid-a")
    from immich_memories.people.registry_store import read_document, write_document

    # Set the registry's own birth_date directly, as the store scan/editor would.
    with store.begin() as connection:
        document = read_document(connection)
        for entry in document["people"]:
            if "kid-a" in entry.get("ids", []):
                entry["birth_date"] = "2018-04-02"
        write_document(connection, document)

    discovery = CandidateDiscovery(config, _FakeRuns(), _FakeAttempts())
    snapshot = discovery._library_snapshot(discovery._config.automation, date(2026, 8, 1), store)

    assert snapshot.people[0].birth_date == date(2018, 4, 2)
