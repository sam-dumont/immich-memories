"""Partner-shared pictures stay out of every path that reads one account's library (#2352).

Immich's partner sharing puts a connected account's pictures in the primary's own search
results. `generate` already drops them (#2143); `prepare`, `--ask` preparation, the season
and holiday counts of automation, trip discovery and the special-days scan read the same
search and must count only the account's own pictures.

The server is an in-process fake over HTTP. Both keys see both libraries, as two partners
sharing with each other do; `/search/statistics` counts everything a key sees, with no owner
filter, as Immich's does.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import httpx
import pytest

from immich_memories.api.sync_client import SyncImmichClient
from immich_memories.config_loader import Config
from immich_memories.timeperiod import DateRange

URL = "https://immich.example.test"
KEYS = {"primary": "primary-" * 4, "partner": "partner-" * 4}
USERS = {key: f"user-{name}" for name, key in KEYS.items()}
# Far enough from the home base below for any picture there to be a trip.
HOME = (50.0, 4.0)
AWAY = (41.0, 2.0)


def _picture(asset_id: str, owner: str, taken: datetime, where=HOME) -> dict:
    return {
        "id": asset_id,
        "ownerId": f"user-{owner}",
        "type": "IMAGE",
        "originalFileName": f"IMG_{asset_id}.HEIC",
        "fileCreatedAt": taken.isoformat(),
        "fileModifiedAt": taken.isoformat(),
        "localDateTime": taken.replace(tzinfo=None).isoformat() + ".000Z",
        "updatedAt": taken.isoformat(),
        "isFavorite": False,
        "width": 4032,
        "height": 3024,
        "checksum": f"sum-{asset_id}",
        "exifInfo": {
            "make": "Apple",
            "model": "iPhone",
            "latitude": where[0],
            "longitude": where[1],
            "city": "Elsewhere" if where == AWAY else "Home",
            "country": "Nowhere",
        },
        "people": [],
    }


def _taken(row: dict) -> datetime:
    return datetime.fromisoformat(row["fileCreatedAt"])


def _bound(value: str | None, default: datetime) -> datetime:
    if not value:
        return default
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@dataclass
class SharedLibrary:
    """Every picture of both accounts; each key sees all of them through partner sharing."""

    pictures: list[dict] = field(default_factory=list)

    def handler(self, request: httpx.Request) -> httpx.Response:
        user = USERS[request.headers["x-api-key"]]
        path = request.url.path
        if path.endswith("/users/me"):
            return httpx.Response(200, json={"id": user, "email": f"{user}@example.test"})
        if path.endswith("/api-keys/me"):
            return httpx.Response(200, json={"permissions": ["all"]})
        if path.endswith("/search/metadata") or path.endswith("/search/statistics"):
            query = json.loads(request.content)
            after = _bound(query.get("takenAfter"), datetime.min.replace(tzinfo=UTC))
            before = _bound(query.get("takenBefore"), datetime.max.replace(tzinfo=UTC))
            rows = [
                row
                for row in self.pictures
                if after <= _taken(row) <= before and query.get("type") in (None, row["type"])
            ]
            if path.endswith("/statistics"):
                return httpx.Response(200, json={"total": len(rows)})
            return httpx.Response(
                200, json={"assets": {"items": rows, "total": len(rows), "nextPage": None}}
            )
        return httpx.Response(200, json=[])


@pytest.fixture
def library(monkeypatch) -> SharedLibrary:
    server = SharedLibrary()
    real_client = httpx.AsyncClient
    # WHY: the Immich HTTP boundary; every request goes to the in-process fake above.
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(server.handler), **kwargs),
    )
    return server


def _client(name: str = "primary") -> SyncImmichClient:
    return SyncImmichClient(base_url=URL, api_key=KEYS[name], api_version="v2")


def _config(tmp_path, **sections) -> Config:
    return Config(
        immich={
            "url": URL,
            "api_key": KEYS["primary"],
            "api_version": "v2",
            "accounts": {"partner": {"url": URL, "api_key": KEYS["partner"], "api_version": "v2"}},
        },
        cache={"directory": str(tmp_path / "cache")},
        trips={"homebase_latitude": HOME[0], "homebase_longitude": HOME[1]},
        **sections,
    )


AUGUST_15 = datetime(2025, 8, 15, 12, tzinfo=UTC)


def _mixed_august(library: SharedLibrary) -> None:
    library.pictures += [
        _picture("own-1", "primary", AUGUST_15),
        _picture("own-2", "primary", AUGUST_15 + timedelta(minutes=5)),
        _picture("partners", "partner", AUGUST_15 + timedelta(minutes=10)),
    ]


@pytest.mark.feature("sources.partner-shared-excluded")
def test_prepare_counts_only_the_accounts_own_pictures(tmp_path, library):
    from immich_memories.analysis.prepare_scope import eligible_source

    _mixed_august(library)
    window = DateRange(datetime(2025, 8, 1), datetime(2025, 8, 31, 23, 59, 59))

    with _client() as client:
        _scope, sources, assets = eligible_source(client, _config(tmp_path), [window])

    assert sorted(source.id for source in sources) == ["own-1", "own-2"]
    assert sorted(asset.id for asset in assets) == ["own-1", "own-2"]


@pytest.mark.feature("sources.partner-shared-excluded")
def test_ask_preparation_counts_only_the_accounts_own_pictures(tmp_path, library):
    from immich_memories.db import open_store
    from immich_memories.free_text.linking import WhenLink
    from immich_memories.free_text.preparation import assess

    _mixed_august(library)
    config = _config(tmp_path)
    when = WhenLink(start=date(2025, 8, 1), end=date(2025, 8, 31))

    with _client() as client:
        readiness = assess(client, config, open_store(config), when, today=date(2025, 9, 3))

    assert sorted(asset.id for asset in readiness.missing) == ["own-1", "own-2"]


@pytest.mark.feature("sources.partner-shared-excluded")
def test_household_automation_counts_each_picture_once_for_its_owner(tmp_path, library):
    """The season and holiday counts sum both accounts; a picture both see counts once."""
    from immich_memories.automation.discovery_extras import (
        ExtraPlan,
        ExtraReads,
        read_account_extras,
    )
    from immich_memories.config_models_automation import AutomationConfig

    _mixed_august(library)
    plan = ExtraPlan(
        auto_cfg=AutomationConfig(
            detect_albums=False, detect_person_monthly=False, extra_holidays=["08-15: Party"]
        ),
        # The summer just ended and the party a few weeks ago: both films are due.
        today=date(2025, 9, 3),
        hemisphere="north",
        country=None,
        generated_keys=(),
        canon={},
        close_ids=(),
        birth_dates=lambda _account, _people: {},
    )
    reads = ExtraReads()
    for name in ("primary", "partner"):
        with _client(name) as client:
            read_account_extras(
                client, name, f"user-{name}", [], {}, plan, name == "primary", reads
            )

    assert reads.notes == []
    assert reads.holiday_days[(date(2025, 8, 13), date(2025, 8, 17))] == {date(2025, 8, 15): 3}
    assert reads.season_days[(date(2025, 6, 1), date(2025, 8, 31))] == {date(2025, 8, 15): 3}


def _partners_trip(library: SharedLibrary) -> None:
    """Only the partner went away: three days of pictures far from the home base."""
    library.pictures += [
        _picture(f"away-{day}", "partner", datetime(2025, 7, day, 12, tzinfo=UTC), where=AWAY)
        for day in (10, 11, 12, 13)
    ]
    library.pictures.append(_picture("own-home", "primary", datetime(2025, 7, 11, tzinfo=UTC)))


@pytest.mark.feature("sources.partner-shared-excluded")
def test_trip_discovery_finds_no_trip_in_the_partners_gps(tmp_path, library):
    from immich_memories.analysis.trip_discovery import discover_year_trips

    _partners_trip(library)

    with _client() as client:
        trips = discover_year_trips(client, _config(tmp_path).trips, 2025)

    assert trips == []


@pytest.mark.feature("sources.partner-shared-excluded")
def test_automatic_trip_input_holds_only_the_accounts_own_pictures(tmp_path, library):
    from immich_memories.automation.trip_input_cache import load_or_fetch_trip_assets

    _partners_trip(library)
    window = DateRange(datetime(2025, 1, 1), datetime(2025, 12, 31, 23, 59, 59))

    with _client() as client:
        assets = load_or_fetch_trip_assets(
            client,
            cache_root=tmp_path / "cache",
            server_url=URL,
            buckets=[],
            requested_range=window,
            owner_id="user-primary",
        )

    assert [asset.id for asset in assets] == ["own-home"]


@pytest.mark.feature("sources.partner-shared-excluded")
def test_the_special_days_scan_reads_only_the_accounts_own_pictures(tmp_path, library):
    from immich_memories.cli import special_days_cmd

    _mixed_august(library)
    scanned: dict[int, list[str]] = {}

    def scan_one_year(year, assets, found, *_args):
        scanned[year] = sorted(asset.id for asset in assets)

    # WHY: the config the command reads from the user's home; this run's points at the fake.
    with (
        patch("immich_memories.config.get_config", return_value=_config(tmp_path)),
        # WHY: the per-year scan asks a model about each day; the test reads what it was handed.
        patch.object(special_days_cmd, "_scan_one_year", scan_one_year),
        # WHY: the catalogue lives in the user's store; nothing is carried forward here.
        patch.object(special_days_cmd, "_carried_forward", return_value=[]),
    ):
        special_days_cmd._scan_library(2025, 2025, ())

    assert scanned == {2025: ["own-1", "own-2"]}
