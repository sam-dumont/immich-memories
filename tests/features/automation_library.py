"""A picture-level Immich library and the real CLI, for automation feature tests.

Every question discovery asks Immich (month buckets, people, how many pictures hold these
people between two dates, the pictures of a window, albums, who am I) is answered from one
list of pictures, so the counts a detector sees agree with each other the way a real
server's do. The client is autospecced from the real one, so a call it would refuse fails.

The commands run through `immich-memories --config <file> ...` in-process: the config file,
the store, the attempt history and the printed output are the production ones. The
clock and the `generate` child are the only other things a test may replace.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import yaml
from click.testing import CliRunner, Result

from immich_memories.api.compatibility import ResolvedApiVersion
from immich_memories.api.models import Asset, AssetType, Person, TimeBucket, UserInfo
from immich_memories.api.permissions import ApiKeyCapabilities
from tests.immich_fakes import fake_immich_client

OWNER = "owner-0001"


@dataclass(frozen=True, slots=True)
class Shot:
    """One picture: when it was taken (wall clock) and who is in it."""

    taken: datetime
    people: tuple[str, ...] = ()


@dataclass
class Library:
    """Pictures, people and albums one Immich account holds."""

    shots: list[Shot] = field(default_factory=list)
    people: list[Person] = field(default_factory=list)
    albums: list[dict[str, Any]] = field(default_factory=list)

    def person(self, person_id: str, name: str, birth: date | None = None) -> Library:
        self.people.append(
            Person(
                id=person_id,
                name=name,
                thumbnailPath=f"/thumbs/{person_id}.jpg",
                birthDate=datetime.combine(birth, time()) if birth else None,
            )
        )
        return self

    def on(self, day: date, count: int = 1, people: tuple[str, ...] = ()) -> Library:
        """``count`` pictures taken on ``day``, a minute apart from noon."""
        noon = datetime.combine(day, time(12))
        self.shots.extend(Shot(noon + timedelta(minutes=i), people) for i in range(count))
        return self

    def across(self, first: date, days: int, count: int, people: tuple[str, ...] = ()) -> Library:
        """``count`` pictures spread evenly over ``days`` days from ``first``."""
        for i in range(count):
            self.on(first + timedelta(days=i % days), 1, people)
        return self

    def month(self, month: str, count: int, people: tuple[str, ...] = ()) -> Library:
        """``count`` pictures across the first 20 days of ``month`` (YYYY-MM)."""
        first = date.fromisoformat(f"{month}-01")
        return self.across(first, 20, count, people)

    def album(self, album_id: str, name: str, count: int, first: date, last: date) -> Library:
        self.albums.append(
            {
                "id": album_id,
                "albumName": name,
                "assetCount": count,
                "shared": False,
                "startDate": f"{first.isoformat()}T09:00:00.000Z",
                "endDate": f"{last.isoformat()}T18:00:00.000Z",
                "albumUsers": [{"user": {"id": OWNER}, "role": "owner"}],
            }
        )
        return self

    # ── what the client answers ──────────────────────────────────────────

    def _within(
        self, after: datetime | None, before: datetime | None, people: tuple[str, ...] = ()
    ) -> list[Shot]:
        return [
            shot
            for shot in self.shots
            if (after is None or shot.taken >= _naive(after))
            and (before is None or shot.taken <= _naive(before))
            and all(person in shot.people for person in people)
        ]

    def _assets(self, shots: list[Shot]) -> list[Asset]:
        return [
            Asset(
                id=f"asset-{index:05d}",
                type=AssetType.IMAGE,
                ownerId=OWNER,
                fileCreatedAt=shot.taken.replace(tzinfo=UTC),
                fileModifiedAt=shot.taken.replace(tzinfo=UTC),
                localDateTime=shot.taken.replace(tzinfo=UTC),
                updatedAt=shot.taken.replace(tzinfo=UTC),
                originalFileName=f"IMG_{index:05d}.JPG",
            )
            for index, shot in enumerate(shots)
        ]

    def _buckets(self, **_filters: object) -> list[TimeBucket]:
        months: dict[str, int] = {}
        for shot in self.shots:
            key = f"{shot.taken:%Y-%m}-01T00:00:00.000Z"
            months[key] = months.get(key, 0) + 1
        return [TimeBucket(count=n, timeBucket=key) for key, n in sorted(months.items())]

    def _people(self, *_hidden: object, **_flags: object) -> list[Person]:
        return list(self.people)

    def _count(
        self,
        person_ids: Any,
        taken_after: datetime | None = None,
        taken_before: datetime | None = None,
        **_scope: object,
    ) -> int:
        # Immich's statistics with personIds count the pictures holding all of them.
        return len(self._within(taken_after, taken_before, tuple(person_ids)))

    def _range_assets(self, date_range: Any, *_progress: object) -> list[Asset]:
        return self._assets(self._within(date_range.start, date_range.end))

    def _person_assets(self, person_id: str, date_range: Any, *_progress: object) -> list[Asset]:
        return self._assets(self._within(date_range.start, date_range.end, (person_id,)))

    def client(self) -> Any:
        """An Immich client, built from the real one's signatures, serving this library."""
        client = fake_immich_client()
        client.__enter__.return_value = client
        client.get_api_version.return_value = ResolvedApiVersion.V2
        client.get_key_capabilities.return_value = ApiKeyCapabilities(frozenset({"all"}))
        client.get_current_user.return_value = UserInfo(
            id=OWNER, email="owner@example.test", name="Owner"
        )
        client.get_time_buckets.side_effect = self._buckets
        client.get_all_people.side_effect = self._people
        client.get_albums.side_effect = lambda: list(self.albums)
        client.count_assets_with_people.side_effect = self._count
        client.get_assets_for_date_range.side_effect = self._range_assets
        client.get_assets_for_person_and_date_range.side_effect = self._person_assets
        return client


def _naive(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(tzinfo=None) if moment.tzinfo else moment


# ── the install ──────────────────────────────────────────────────────────


def write_config(
    root: Path,
    *,
    immich_url: str = "https://immich.example.test",
    automation: dict[str, Any] | None = None,
    home_base: bool = False,
    **sections: Any,
) -> Path:
    """A config file whose store, cache and films all live under ``root``.

    Trips are off unless a test says otherwise: they read Immich's search in pages, a
    route the trip feature test drives over HTTP instead.
    """
    root.mkdir(parents=True, exist_ok=True)
    config: dict[str, Any] = {
        "immich": {"url": immich_url, "api_key": "feature-test-key"},
        "cache": {"database": str(root / "store.db"), "directory": str(root / "cache")},
        "output": {"directory": str(root / "films")},
        "trips": (
            {"homebase_latitude": 50.8417, "homebase_longitude": 4.3624} if home_base else {}
        ),
        # These tests are about automation, not sign-in; a test of sign-in passes its own `auth`.
        "advanced": {
            "auth": {"enabled": False},
            "automation": {"detect_trips": False, **(automation or {})},
        },
    }
    for key, value in sections.items():
        if key in ("notifications", "server", "auth"):
            config["advanced"][key] = value
        else:
            config[key] = value
    path = root / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False))
    path.chmod(0o600)
    return path


@contextmanager
def immich_holding(library: Library) -> Iterator[Any]:
    """Every Immich connection the app opens reaches ``library``."""
    client = library.client()
    # Discovery opens accounts through one import and the preflight check through another.
    # WHY: the Immich server; both imports get the same library-backed client.
    with (
        patch("immich_memories.api.accounts.SyncImmichClient", return_value=client),
        patch("immich_memories.api.immich.SyncImmichClient", return_value=client),
    ):
        yield client


@contextmanager
def today_is(day: date) -> Iterator[None]:
    """Discovery runs on ``day``: the detectors' calendar, not the attempt history's."""

    class _Today(date):
        @classmethod
        def today(cls) -> date:  # type: ignore[override]
            return day

    # WHY: the wall clock; each promise lives on particular days of the year.
    with patch("immich_memories.automation.candidate_discovery.date", _Today):
        yield


def cli(config_path: Path, *args: str) -> Result:
    """`immich-memories --config <config_path> <args>`, as a user types it."""
    from immich_memories.cli import main

    return CliRunner().invoke(main, ["--config", str(config_path), *args])


def suggestions(config_path: Path, library: Library, today: date) -> list[dict[str, Any]]:
    """Every candidate `auto suggest --json` lists on ``today``."""
    with immich_holding(library), today_is(today):
        result = cli(config_path, "auto", "suggest", "--json", "--limit", "200")
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def suggest_text(config_path: Path, library: Library, today: date) -> str:
    """What `auto suggest` prints for a person on ``today``."""
    with immich_holding(library), today_is(today):
        result = cli(config_path, "auto", "suggest", "--limit", "200")
    assert result.exit_code == 0, result.output
    return result.stdout


def of_category(rows: list[dict[str, Any]], category: str) -> list[dict[str, Any]]:
    return [row for row in rows if row["category"] == category]


# ── what leaves the machine ──────────────────────────────────────────────


class LocalHttp:
    """A loopback HTTP server that answers fixed JSON per path and records every request.

    Stands in for the far side of a real HTTP call (Immich's reverse geocoder, an Apprise
    JSON target): the app's own HTTP client does the talking.
    """

    def __init__(self, answers: dict[str, Any] | None = None) -> None:
        self.answers = answers or {}
        self.requests: list[tuple[str, str, Any]] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    body: Any = json.loads(raw) if raw else None
                except ValueError:
                    body = raw.decode("utf-8", "replace")
                path = self.path.split("?", 1)[0]
                server.requests.append((self.command, path, body))
                payload = json.dumps(server.answers.get(path, {})).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = _answer  # noqa: N815
            do_POST = _answer  # noqa: N815

            def log_message(self, _format: str, *args: object) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def posted(self) -> list[Any]:
        return [body for method, _path, body in self.requests if method == "POST"]

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


# ── what the user set up with other commands ─────────────────────────────


def import_people(config_path: Path, people: dict[str, tuple[str, str | None]]) -> None:
    """`people import` a registry: person id -> (name, closeness tier)."""
    document = {
        "people": [
            {
                "ids": [person_id],
                "name": name,
                "birth_date": None,
                "inferred": {"tier": tier, "counts_reliable": False, "evidence": {}, "links": []},
                "confirmed": {"role": None, "links": [], "notes": None},
                "origin": "immich",
            }
            for person_id, (name, tier) in people.items()
        ]
    }
    source = config_path.parent / "people-import.yaml"
    source.write_text(yaml.safe_dump(document, sort_keys=False))
    result = cli(config_path, "people", "import", "--from", str(source))
    assert result.exit_code == 0, result.output


def import_special_days(config_path: Path, *days: tuple[date, int]) -> None:
    """`days-import` a catalogue of judged days: (day, photos)."""
    records = [
        {"day": day.isoformat(), "title": f"A day in {day.year}", "photos": photos}
        for day, photos in days
    ]
    source = config_path.parent / "days-import.json"
    source.write_text(json.dumps(records))
    result = cli(config_path, "days-import", "--from", str(source))
    assert result.exit_code == 0, result.output


def record_film(
    config_path: Path,
    memory_type: str,
    memory_key: str,
    *,
    source: str = "manual",
    category: str | None = None,
    people: tuple[str, ...] = (),
    hours_ago: float = 40 * 24,
) -> None:
    """A completed film in the run history, as a finished `generate` leaves it."""
    from immich_memories.config_loader import Config
    from immich_memories.db import open_store
    from immich_memories.tracking.models import RunMetadata
    from immich_memories.tracking.run_database import RunDatabase

    finished = datetime.now(tz=UTC) - timedelta(hours=hours_ago)
    run_id = f"film-{uuid4().hex[:12]}"
    film = config_path.parent / "films" / f"{run_id}.mp4"
    film.parent.mkdir(parents=True, exist_ok=True)
    film.write_bytes(b"film")
    RunDatabase(open_store(Config.from_yaml(config_path))).save_run(
        RunMetadata(
            run_id=run_id,
            created_at=finished - timedelta(minutes=10),
            completed_at=finished,
            status="completed",
            source=source,
            memory_type=memory_type,
            memory_key=memory_key,
            memory_category=category,
            memory_people=people,
            output_path=str(film),
        )
    )
