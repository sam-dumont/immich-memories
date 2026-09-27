"""The library a brief is written against: the named people, albums and trips Immich holds."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from immich_memories.config_loader import Config
from immich_memories.web.dependencies import current_config

router = APIRouter(prefix="/api/v1", tags=["library"])


class NamedPerson(BaseModel):
    id: str
    name: str


class AlbumChoice(BaseModel):
    id: str
    name: str
    asset_count: int


class TripChoice(BaseModel):
    # 1-based, in discovery order: the number `generate --trip-index` takes.
    index: int
    place: str
    start: date
    end: date
    days: int
    pictures: int


def immich_client(config: Annotated[Config, Depends(current_config)]) -> Iterator[Any]:
    """A client for this request, closed after it; the API key stays on the server."""
    from immich_memories.api.sync_client import SyncImmichClient

    with SyncImmichClient(
        base_url=config.immich.url,
        api_key=config.immich.api_key,
        api_version=config.immich.api_version,
    ) as client:
        yield client


@router.get("/people", response_model=list[NamedPerson])
def people(client: Annotated[Any, Depends(immich_client)]) -> list[NamedPerson]:
    """Everyone Immich has a name for, alphabetically: the names `--person` takes."""
    named = [NamedPerson(id=p.id, name=p.name) for p in client.get_all_people() if p.name]
    return sorted(named, key=lambda person: person.name.casefold())


@router.get("/albums", response_model=list[AlbumChoice])
def albums(client: Annotated[Any, Depends(immich_client)]) -> list[AlbumChoice]:
    """The albums a film can be made from, largest first; `--from-album` takes the id."""
    return sorted(
        (
            AlbumChoice(id=a.id, name=a.name, asset_count=a.asset_count)
            for a in client.list_albums()
        ),
        key=lambda album: (-album.asset_count, album.name.casefold()),
    )


TripFinder = Callable[[int, list[str]], list[Any]]


def trip_finder(
    config: Annotated[Config, Depends(current_config)],
    client: Annotated[Any, Depends(immich_client)],
) -> TripFinder:
    """Discovery as `generate --memory-type trip` runs it, so an index names the same trip."""
    from immich_memories.analysis.trip_detection import geocoder_for
    from immich_memories.analysis.trip_discovery import discover_year_trips
    from immich_memories.processing.clip_caption import resolve_caption_locale

    geocoder = geocoder_for(
        enabled=config.network.geocoding,
        language=resolve_caption_locale(config.title_screens.locale),
    )

    def find(year: int, people: list[str]) -> list[Any]:
        return discover_year_trips(
            client, config.trips, year, person_names=people or None, geocoder=geocoder
        )

    return find


@router.get("/trips", response_model=list[TripChoice])
def trips(
    year: int,
    find: Annotated[TripFinder, Depends(trip_finder)],
    person: Annotated[list[str] | None, Query()] = None,
) -> list[TripChoice]:
    """The trips that overlap a year, as `generate` lists them before it cuts one."""
    return [
        TripChoice(
            index=number,
            place=trip.location_name,
            start=trip.start_date,
            end=trip.end_date,
            days=(trip.end_date - trip.start_date).days + 1,
            pictures=trip.asset_count,
        )
        for number, trip in enumerate(find(year, person or []), 1)
    ]


class SpecialDay(BaseModel):
    day: date
    # Set when two catalogued events share the day: `--event-id` picks between them.
    event_id: str | None
    name: str
    # How many years ago, when its anniversary is due now; None for every other day.
    years_ago: int | None


def special_days_catalogue() -> Path:
    from immich_memories.automation.catalogue import default_catalogue_path

    return default_catalogue_path()


def today() -> date:
    return date.today()


def _anniversary_rank(years: int) -> int:
    """How round an anniversary is, ranked the way `anniversaries_due` sorts."""
    if years < 1:
        return 3
    return 0 if years % 10 == 0 else 1 if years % 5 == 0 else 2


@router.get("/special-days", response_model=list[SpecialDay])
def special_days(
    catalogue: Annotated[Path, Depends(special_days_catalogue)],
    on: Annotated[date, Depends(today)],
) -> list[SpecialDay]:
    """The days `discover-days` catalogued, anniversaries due first, then the rest.

    A scheduled run only proposes a day on its anniversary; someone at the brief wants a memory
    now, so every catalogued day is offered below the due ones. A day the model could not name
    is left out: there is nothing truthful to put on its title card.
    """
    from immich_memories.automation.catalogue import entries_from
    from immich_memories.automation.special_day_scan import anniversaries_due

    def name(entry: Any) -> str:
        return entry.title.strip() or entry.what.strip()

    entries = [entry for entry in entries_from(catalogue) if name(entry)]
    due = anniversaries_due(entries, on)
    seen = {id(entry) for entry, _ in due}
    rest = sorted(
        (entry for entry in entries if id(entry) not in seen),
        key=lambda entry: (_anniversary_rank(on.year - entry.day.year), -entry.day.toordinal()),
    )
    return [
        SpecialDay(day=entry.day, event_id=entry.event_id, name=name(entry), years_ago=years)
        for entry, years in (*due, *((entry, None) for entry in rest))
    ]


class HolidayChoice(BaseModel):
    # What `--holiday` takes.
    key: str
    name: str


@router.get("/holidays", response_model=list[HolidayChoice])
def holidays(lang: str = "en") -> list[HolidayChoice]:
    """The holidays the pipeline resolves, named in the page's language; any MM-DD works too."""
    from immich_memories.memory_types.factory import holiday_choices

    return [HolidayChoice(key=key, name=name) for key, name in holiday_choices(lang).items()]
