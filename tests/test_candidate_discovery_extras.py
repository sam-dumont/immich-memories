"""One discovery pass over a fake Immich: what the rc.6 detectors propose (#2227-#2232)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

import pytest

from immich_memories.api.accounts import OpenAccount
from immich_memories.api.compatibility import ResolvedApiVersion
from immich_memories.api.models import Person, TimeBucket, UserInfo
from immich_memories.automation import candidate_discovery as discovery_module
from immich_memories.automation.candidate_discovery import CandidateDiscovery
from immich_memories.automation.candidates import CandidateCategory
from immich_memories.config_loader import Config
from immich_memories.db import open_store
from immich_memories.generate import GenerationParams, build_memory_key
from immich_memories.people.companion import add_confirmed_person
from immich_memories.tracking.models import RunMetadata
from immich_memories.tracking.run_database import RunDatabase

TODAY = date.today()


def _month_ago(months: int) -> date:
    year, month = TODAY.year, TODAY.month - months
    while month < 1:
        year, month = year - 1, month + 12
    return date(year, month, 1)


@dataclass
class _Asset:
    file_created_at: object
    local_date_time: object = None


@dataclass
class _Immich:
    """The slice of `SyncImmichClient` discovery reads."""

    buckets: list[TimeBucket]
    people: list[Person]
    albums: list[dict]
    person_pictures: dict[str, list[date]]
    asked_for_albums: int = field(default=0)

    def get_time_buckets(self, **_kwargs):
        return self.buckets

    def get_all_people(self, with_hidden: bool = False):
        return self.people

    def count_assets_with_people(self, person_ids, taken_after=None, taken_before=None):
        return 0

    def get_albums(self):
        self.asked_for_albums += 1
        return self.albums

    def get_assets_for_date_range(self, _span, _progress=None):
        return []

    def get_assets_for_person_and_date_range(self, person_id, _span, _progress=None):
        return [_Asset(file_created_at=_at(d)) for d in self.person_pictures.get(person_id, [])]

    def close(self):
        pass


def _at(day: date):
    from datetime import datetime

    return datetime(day.year, day.month, day.day, 12)


class _Runs:
    def get_generated_memory_keys(self) -> set[str]:
        return set()

    def get_last_run_of_type(self, memory_type, source=None):
        return None

    def get_last_run_of_category(self, memory_category, source=None):
        return None


class _Attempts:
    def consecutive_failures_by_key(self) -> dict:
        return {}


def _discover(monkeypatch, immich: _Immich, role: str | None, completed_run=None):
    config = Config(
        immich={"url": "https://immich.example.test", "api_key": "key"},
        automation={"detect_trips": False},
    )
    account = OpenAccount(
        name="primary",
        client=immich,  # type: ignore[arg-type]
        user=UserInfo(id="user-me", email="me@example.test"),
        api_version=ResolvedApiVersion.V2,
    )
    # WHY: the Immich client boundary; the real opener is covered in test_immich_accounts.py.
    monkeypatch.setattr(
        discovery_module, "open_accounts", lambda _immich, _names: {"primary": account}
    )
    # WHY: asks Immich's geodata server where the home base is; no home base is configured here.
    monkeypatch.setattr(discovery_module, "known_home_country", lambda _config: None)
    store = open_store(config)
    if role:
        add_confirmed_person(store, "Kid A", person_id="kid", role=role)
    runs = RunDatabase(store)
    if completed_run is not None:
        runs.save_run(completed_run)
    return CandidateDiscovery(config, runs, _Attempts()).discover(limit=20, recent_auto_runs=[])


def _library(person_days: list[date]) -> _Immich:
    return _Immich(
        buckets=[TimeBucket(count=80, timeBucket=_month_ago(n).isoformat()) for n in range(1, 8)],
        people=[Person(id="kid", name="Kid A", thumbnailPath="/t.jpg")],
        albums=[
            {
                "id": "album-1",
                "albumName": "Lisbon",
                "assetCount": 42,
                "shared": False,
                "startDate": "2025-05-01T09:00:00.000Z",
                "endDate": "2025-05-05T18:00:00.000Z",
                "albumUsers": [{"user": {"id": "user-me"}, "role": "owner"}],
            }
        ],
        person_pictures={"kid": person_days},
    )


def test_one_pass_proposes_an_album_a_close_persons_month_and_backfill(monkeypatch):
    last_month = _month_ago(1)
    days = [last_month + timedelta(days=i) for i in range(0, 20, 2)]  # ten days
    pictures = days * 2  # twenty pictures

    result = _discover(monkeypatch, _library(pictures), role="son")

    by_category = {c.category: c for c in result.candidates}
    assert by_category[CandidateCategory.ALBUM].extra_params["album_id"] == "album-1"
    assert by_category[CandidateCategory.PERSON_MONTHLY].person_names == ["Kid A"]
    assert CandidateCategory.BACKFILL in by_category
    # One of each: the cap per type holds even with six quiet months to film.
    assert [c.category for c in result.candidates].count(CandidateCategory.BACKFILL) == 1


def test_a_person_the_registry_does_not_call_close_gets_no_monthly(monkeypatch):
    last_month = _month_ago(1)
    pictures = [last_month + timedelta(days=i) for i in range(10)] * 2

    result = _discover(monkeypatch, _library(pictures), role=None)

    assert CandidateCategory.PERSON_MONTHLY not in {c.category for c in result.candidates}


def test_no_home_base_says_so_instead_of_proposing_a_season(monkeypatch):
    result = _discover(monkeypatch, _library([]), role=None)

    assert any("home base" in note for note in result.notes)
    assert CandidateCategory.SEASON not in {c.category for c in result.candidates}


def test_a_server_that_cannot_list_albums_costs_the_album_not_the_run(monkeypatch):
    immich = _library([])

    def _boom():
        raise ConnectionError("albums unavailable")

    immich.get_albums = _boom  # type: ignore[method-assign]

    result = _discover(monkeypatch, immich, role=None)

    assert any("albums" in note for note in result.notes)
    assert result.candidates


def test_switching_the_new_detectors_off_proposes_none_of_them_and_asks_for_nothing(monkeypatch):
    immich = _library([_month_ago(1) + timedelta(days=i) for i in range(10)] * 2)
    config = Config(
        immich={"url": "https://immich.example.test", "api_key": "key"},
        automation={
            "detect_trips": False,
            "detect_seasons": False,
            "detect_holidays": False,
            "detect_albums": False,
            "detect_person_monthly": False,
            "backfill_months": False,
        },
    )
    account = OpenAccount(
        name="primary",
        client=immich,  # type: ignore[arg-type]
        user=UserInfo(id="user-me", email="me@example.test"),
        api_version=ResolvedApiVersion.V2,
    )
    # WHY: the Immich client boundary, as in _discover above.
    monkeypatch.setattr(discovery_module, "open_accounts", lambda _i, _n: {"primary": account})

    result = CandidateDiscovery(config, _Runs(), _Attempts()).discover(
        limit=20, recent_auto_runs=[]
    )

    new = {
        CandidateCategory.SEASON,
        CandidateCategory.HOLIDAY,
        CandidateCategory.ALBUM,
        CandidateCategory.BACKFILL,
        CandidateCategory.PERSON_MONTHLY,
    }
    assert new.isdisjoint({c.category for c in result.candidates})
    assert immich.asked_for_albums == 0


@pytest.mark.parametrize("timestamp_key", [False, True])
@pytest.mark.parametrize("person_name", ["Kid A", None])
def test_completed_manual_month_is_not_proposed_again(
    monkeypatch, tmp_path, timestamp_key, person_name
):
    first = _month_ago(1)
    last = TODAY.replace(day=1) - timedelta(days=1)
    params = GenerationParams(
        clips=[],
        output_path=tmp_path / "manual.mp4",
        config=Config(),
        memory_type="monthly_highlights",
        person_name=person_name,
        date_start=datetime.combine(first, time.min) if timestamp_key else first,
        date_end=datetime.combine(last, time(23, 59, 59)) if timestamp_key else last,
    )
    completed = RunMetadata(
        run_id="manual-month",
        created_at=_at(TODAY),
        status="completed",
        source="manual",
        memory_type=params.memory_type,
        memory_key=build_memory_key(params),
        date_range_start=first,
        date_range_end=last,
        output_path=str(params.output_path),
    )
    pictures = [first + timedelta(days=i) for i in range(10)] * 2

    result = _discover(monkeypatch, _library(pictures), role="son", completed_run=completed)

    category = CandidateCategory.PERSON_MONTHLY if person_name else CandidateCategory.MONTHLY_REVIEW
    assert category not in {c.category for c in result.candidates}
    assert result.candidates  # Unrelated memories remain available.
    # Matching history must not rewrite the original identity on disk.
    assert RunDatabase().get_run("manual-month").memory_key == completed.memory_key
