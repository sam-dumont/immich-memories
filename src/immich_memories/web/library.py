"""The library a brief is written against: the named people and the albums Immich holds."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends
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
    """The albums a film can be made from, the names `--from-album` takes."""
    return sorted(
        (
            AlbumChoice(id=a.id, name=a.name, asset_count=a.asset_count)
            for a in client.list_albums()
        ),
        key=lambda album: album.name.casefold(),
    )
