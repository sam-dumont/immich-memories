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
    # person id -> years they have pictures in, for windowed statistics
    picture_years: dict[str, set[int]] = field(default_factory=dict)
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

    def get_albums(self):
        return []

    def count_assets_with_people(self, person_ids, taken_after=None, taken_before=None):
        if not person_ids:
            return 0
        years = set.intersection(*(self.picture_years.get(p, set()) for p in person_ids))
        return sum(1 for y in years if taken_after.year <= y <= taken_before.year)

    def close(self):
        self.closed = True


class _FakeRuns:
    def get_generated_memory_keys(self) -> set[str]:
        return set()

    def get_last_run_of_type(self, memory_type: str, source: str | None = None):
        return None

    def get_last_run_of_category(self, memory_category: str, source: str | None = None):
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


def _trip_assets(start: date, days: int) -> list:
    from datetime import UTC, datetime, timedelta

    from immich_memories.api.models import Asset, AssetType, ExifInfo

    assets = []
    for day in range(days):
        for hour in range(9, 21):
            taken = datetime.combine(start + timedelta(days=day), datetime.min.time(), UTC)
            taken += timedelta(hours=hour)
            assets.append(
                Asset(
                    id=f"trip-{day}-{hour}",
                    type=AssetType.IMAGE,
                    fileCreatedAt=taken,
                    fileModifiedAt=taken,
                    updatedAt=taken,
                    exifInfo=ExifInfo(
                        latitude=43.30, longitude=5.37, city="Seaside", country="Elsewhere"
                    ),
                )
            )
    return assets


@pytest.mark.parametrize("accounts", [[], ["primary", "partner"]])
def test_a_trip_is_still_suggested_from_the_primary_when_accounts_are_selected(
    monkeypatch, accounts
):
    """Trips stay primary-only: selecting a second account must not lose them."""
    from datetime import timedelta

    today = date.today()
    trip = _trip_assets(today - timedelta(days=40), 12)
    primary = _FakeClient(
        buckets=[TimeBucket(count=len(trip), timeBucket="2026-01-01")], people=[], counts={}
    )
    partner = _FakeClient(
        buckets=[TimeBucket(count=4, timeBucket="2026-01-01")], people=[], counts={}
    )
    opened = {"primary": _open_account("primary", primary)}
    if accounts:
        opened["partner"] = _open_account("partner", partner)
    _patch_open_accounts(monkeypatch, opened)
    # WHY: the trailing-year bulk read from Immich; its cache has its own tests.
    monkeypatch.setattr(discovery_module, "load_or_fetch_trip_assets", lambda *_a, **_k: trip)
    config = _config(accounts)
    config.automation.detect_trips = True
    config.trips.homebase_latitude = 50.85
    config.trips.homebase_longitude = 4.35

    found = CandidateDiscovery(config, _FakeRuns(), _FakeAttempts()).discover(
        limit=None, recent_auto_runs=[]
    )

    trips = [c for c in found.candidates if c.memory_type == "trip"]
    assert len(trips) == 1
    assert "accounts" not in trips[0].extra_params


def _kim_in_other_years(birth_date=None):
    return _FakeClient(
        buckets=[],
        people=[Person(id="kim", name="Kim", thumbnailPath="/t.jpg", birthDate=birth_date)],
        counts={"kim": 273},
        picture_years={"kim": {2019, 2020}},
    )


def test_a_person_with_pictures_only_in_other_years_gets_no_spotlight_for_last_year(monkeypatch):
    kim = _kim_in_other_years()
    _patch_open_accounts(monkeypatch, {"primary": _open_account("primary", kim)})
    store = open_store(_config([]))
    discovery = CandidateDiscovery(_config([]), _FakeRuns(), _FakeAttempts())

    snapshot = discovery._library_snapshot(discovery._config.automation, date(2026, 8, 1), store)

    assert snapshot.spotlight_counts == {"kim": 0}


def test_a_person_with_pictures_last_year_keeps_the_spotlight_with_that_years_count(monkeypatch):
    kim = _kim_in_other_years()
    kim.picture_years["kim"] = {2019, 2025}
    _patch_open_accounts(monkeypatch, {"primary": _open_account("primary", kim)})
    store = open_store(_config([]))
    discovery = CandidateDiscovery(_config([]), _FakeRuns(), _FakeAttempts())

    snapshot = discovery._library_snapshot(discovery._config.automation, date(2026, 8, 1), store)

    assert snapshot.spotlight_counts == {"kim": 1}


def test_a_birthday_is_counted_over_the_windows_its_film_reads(monkeypatch):
    from datetime import datetime

    kim = _kim_in_other_years(birth_date=datetime(2000, 7, 10))
    kim.picture_years["kim"] = {2026}
    _patch_open_accounts(monkeypatch, {"primary": _open_account("primary", kim)})
    store = open_store(_config([]))
    discovery = CandidateDiscovery(_config([]), _FakeRuns(), _FakeAttempts())

    snapshot = discovery._library_snapshot(discovery._config.automation, date(2026, 8, 1), store)
    kim.picture_years["kim"] = {2019}
    stale = discovery._library_snapshot(discovery._config.automation, date(2026, 8, 1), store)

    assert snapshot.birthday_counts == {"kim": 1}
    assert stale.birthday_counts == {"kim": 0}


def test_a_pair_and_a_group_are_counted_in_last_year_only(monkeypatch):
    kim = _kim_in_other_years()
    kim.people.append(Person(id="robin", name="Robin", thumbnailPath="/t.jpg"))
    kim.picture_years["robin"] = {2019, 2020}
    _patch_open_accounts(monkeypatch, {"primary": _open_account("primary", kim)})
    store = open_store(_config([]))
    discovery = CandidateDiscovery(_config([]), _FakeRuns(), _FakeAttempts())

    snapshot = discovery._library_snapshot(discovery._config.automation, date(2026, 8, 1), store)
    assert snapshot.shared_counts == {}

    kim.picture_years = {"kim": {2025}, "robin": {2025}}
    snapshot = discovery._library_snapshot(discovery._config.automation, date(2026, 8, 1), store)

    assert snapshot.shared_counts == {("kim", "robin"): 1}
