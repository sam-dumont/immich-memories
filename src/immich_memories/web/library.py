"""The library a brief is written against: the named people, albums and trips Immich holds."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from immich_memories.config_loader import Config
from immich_memories.db import Store
from immich_memories.web.answer_cache import AnswerCache, Cached
from immich_memories.web.dependencies import answers, current_config
from immich_memories.web.roster import people_store

router = APIRouter(prefix="/api/v1", tags=["library"])


class NamedPerson(BaseModel):
    id: str
    name: str
    # Pictures the last `people scan` counted for this face; None before a scan reached them.
    pictures: int | None = None


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


def _picture_counts(store: Store) -> dict[str, int]:
    """Each Immich person id's picture count, from the people registry `people scan` writes."""
    from immich_memories.people.account_ids import entry_ids
    from immich_memories.people.companion import load_document, people_entries

    counts: dict[str, int] = {}
    for entry in people_entries(load_document(store)):
        evidence = (entry.get("inferred") or {}).get("evidence") or {}
        if isinstance(evidence.get("count"), int):
            counts.update(dict.fromkeys(entry_ids(entry), evidence["count"]))
    return counts


@router.get("/people", response_model=list[NamedPerson])
def people(
    client: Annotated[Any, Depends(immich_client)],
    registry: Annotated[Store, Depends(people_store)],
) -> list[NamedPerson]:
    """Everyone Immich has a name for, the names `--person` takes: most pictured first.

    The counts are the last people scan's; anyone it has not counted follows alphabetically.
    """
    counts = _picture_counts(registry)
    named = [
        NamedPerson(id=p.id, name=p.name, pictures=counts.get(p.id))
        for p in client.get_all_people()
        if p.name
    ]
    return sorted(named, key=lambda p: (-(p.pictures or -1), p.name.casefold()))


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


def trip_finder(config: Annotated[Config, Depends(current_config)]) -> TripFinder:
    """Discovery as `generate --memory-type trip` runs it, so an index names the same trip.

    It opens its own Immich client: the answer is worked out behind the page, after the request
    that asked for it has finished.
    """
    from immich_memories.analysis.trip_detection import geocoder_for
    from immich_memories.analysis.trip_discovery import discover_year_trips
    from immich_memories.api.sync_client import SyncImmichClient

    geocoder = geocoder_for(config)

    def find(year: int, people: list[str]) -> list[Any]:
        with SyncImmichClient(
            base_url=config.immich.url,
            api_key=config.immich.api_key,
            api_version=config.immich.api_version,
        ) as client:
            return discover_year_trips(
                client, config.trips, year, person_names=people or None, geocoder=geocoder
            )

    return find


class Trips(BaseModel):
    # None until the first discovery of this year has finished.
    trips: list[TripChoice] | None
    computed_at: datetime | None
    refreshing: bool
    error: str | None


def _trip_choices(found: list[Any]) -> list[TripChoice]:
    return [
        TripChoice(
            index=number,
            place=trip.location_name,
            start=trip.start_date,
            end=trip.end_date,
            days=(trip.end_date - trip.start_date).days + 1,
            pictures=trip.asset_count,
        )
        for number, trip in enumerate(found, 1)
    ]


def trips_answer(
    cache: AnswerCache, find: TripFinder, year: int, people: list[str], *, refresh: bool = False
) -> Cached:
    """A year's trips from the answer cache, worked out behind the page when due."""
    named = sorted(people)
    return cache.read(
        f"trips:{year}:{','.join(named)}",
        lambda: {"trips": [t.model_dump(mode="json") for t in _trip_choices(find(year, named))]},
        refresh=refresh,
    )


@router.get("/trips", response_model=Trips)
def trips(
    year: int,
    find: Annotated[TripFinder, Depends(trip_finder)],
    cache: Annotated[AnswerCache, Depends(answers)],
    person: Annotated[list[str] | None, Query()] = None,
    refresh: bool = False,
) -> Trips:
    """The trips that overlap a year, as `generate` lists them before it cuts one.

    Discovery reads the year's GPS and takes a while; the last answer for the year comes back at
    once, and a fresh one is worked out behind it when it is a day old or `refresh` asks.
    """
    got = trips_answer(cache, find, year, person or [], refresh=refresh)
    listed = [TripChoice.model_validate(t) for t in got.value["trips"]] if got.value else None
    return Trips(
        trips=listed, computed_at=got.computed_at, refreshing=got.refreshing, error=got.error
    )


class SpecialDay(BaseModel):
    day: date
    # Set when two catalogued events share the day: `--event-id` picks between them.
    event_id: str | None
    name: str
    # How many years ago, when its anniversary is due now; None for every other day.
    years_ago: int | None


def special_days_catalogue(config: Annotated[Config, Depends(current_config)]) -> list[dict]:
    """The records `discover-days` keeps in the store."""
    from immich_memories.automation.catalogue import load_catalogue
    from immich_memories.db import open_store

    return load_catalogue(open_store(config))


def today() -> date:
    return date.today()


def _anniversary_rank(years: int) -> int:
    """How round an anniversary is, ranked the way `anniversaries_due` sorts."""
    if years < 1:
        return 3
    return 0 if years % 10 == 0 else 1 if years % 5 == 0 else 2


@router.get("/special-days", response_model=list[SpecialDay])
def special_days(
    catalogue: Annotated[list[dict], Depends(special_days_catalogue)],
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


def holiday_country(config: Annotated[Config, Depends(current_config)]) -> str:
    """The country whose calendar a holiday brief keeps: the home base's, as `generate` reads it."""
    from immich_memories.home_country import home_country

    return home_country(config)


@router.get("/holidays", response_model=list[HolidayChoice])
def holidays(
    country: Annotated[str, Depends(holiday_country)], lang: str = "en"
) -> list[HolidayChoice]:
    """The holidays the pipeline resolves: the known ones, named in the page's language, then
    the home country's other public holidays by their own name. Any MM-DD works too."""
    from immich_memories.memory_types.date_builders import holidays_of, resolve_holiday
    from immich_memories.memory_types.factory import holiday_choices

    year = date.today().year
    known = holiday_choices(lang)
    taken = set()
    for key in known:
        try:
            taken.add(resolve_holiday(key, year, country=country))
        except ValueError:
            continue
    public = [name for day, name in sorted(holidays_of(year, country).items()) if day not in taken]
    return [
        *(HolidayChoice(key=key, name=name) for key, name in known.items()),
        *(HolidayChoice(key=name, name=name) for name in dict.fromkeys(public)),
    ]
