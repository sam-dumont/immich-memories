"""The library a free-text request is read against: one row of facts per picture.

Immich's metadata (date, media kind, place names, GPS) comes from the store's
`annotation_assets` rows, which preparation writes from the Immich fetch (`remember_assets`);
a caller holding a fresh fetch remembers it the same way before reading. Captions, the
document head's picture kind, sharpness and recognised faces are the banked facts of the
configured producers, read through `AssetAnnotationFactRepository`. A picture nothing has
prepared still has its date, places and faces.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import sqlalchemy as sa

from immich_memories.config_models_editorial import EditorialConfig
from immich_memories.db import Store, from_db
from immich_memories.db.tables import annotation_assets
from immich_memories.people.context import PersonPromptContext, load_people_prompt_context
from immich_memories.store.asset_annotations import (
    AssetAnnotationFactRepository,
    StoredAssetAnnotationFacts,
)
from immich_memories.store.batches import id_in, in_chunks


@dataclass(frozen=True, slots=True)
class LibraryPerson:
    """Someone in the people file, under the first Immich id they were known by."""

    person_id: str
    name: str
    role: str | None
    birth_date: date | None


@dataclass(frozen=True, slots=True)
class LibraryPicture:
    """What the library holds about one picture."""

    asset_id: str
    taken_at: datetime
    media_kind: str
    caption: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    # The document head's label ("photograph", "screenshot_from_computer"); None when unread.
    picture_kind: str | None = None
    sharpness: float | None = None
    # People-file persons whose face Immich recognised in this picture.
    people: frozenset[str] = frozenset()


@dataclass(frozen=True)
class LibraryView:
    """Every picture in time order, the people file, and the engine's sharpness line."""

    pictures: tuple[LibraryPicture, ...]
    people: Mapping[str, LibraryPerson]
    # The library's 10th-percentile sharpness: the engine calls a picture soft below it.
    sharpness_line: float | None


class LibraryUnavailable(RuntimeError):
    """The store could not be read."""


def read_library(
    store: Store, editorial: EditorialConfig, *, asset_ids: Sequence[str] | None = None
) -> LibraryView:
    """Read the pictures the store knows (only `asset_ids` when given), oldest first."""
    contexts = load_people_prompt_context(store)
    canonical = {person_id: context.person_ids[0] for person_id, context in contexts.items()}
    people = {context.person_ids[0]: _person(context) for context in contexts.values()}
    sources = _sources(store, asset_ids)
    if not sources:
        return LibraryView(pictures=(), people=people, sharpness_line=None)
    batch = AssetAnnotationFactRepository(
        store,
        description_model=editorial.description_model,
        head_versions=editorial.head_versions,
        pixel_producer_key=editorial.pixel_producer_key,
    ).facts_for(tuple(row["asset_id"] for row in sources))
    if batch.unavailable_asset_ids:
        raise LibraryUnavailable("; ".join(batch.warnings) or "the store could not be read")
    facts = batch.as_mapping()
    pictures = sorted(
        (
            _picture(row, taken, facts[row["asset_id"]], canonical)
            for row in sources
            if (taken := from_db(row["taken_at"]))
        ),
        key=lambda picture: (picture.taken_at, picture.asset_id),
    )
    line = next(
        (
            fact.pixel.soft_below
            for fact in facts.values()
            if fact.pixel and fact.pixel.soft_below is not None
        ),
        None,
    )
    return LibraryView(pictures=tuple(pictures), people=people, sharpness_line=line)


def _person(context: PersonPromptContext) -> LibraryPerson:
    try:
        born = date.fromisoformat(context.birth_date) if context.birth_date else None
    except ValueError:
        born = None
    return LibraryPerson(
        person_id=context.person_ids[0], name=context.name, role=context.role, birth_date=born
    )


def _sources(store: Store, asset_ids: Sequence[str] | None) -> list[dict[str, Any]]:
    table = annotation_assets
    query = sa.select(table).where(table.c.taken_at.is_not(None))
    with store.connect() as connection:
        if asset_ids is None:
            return [dict(row._mapping) for row in connection.execute(query)]
        wanted = list(dict.fromkeys(asset_ids))
        return [
            dict(row._mapping)
            for chunk in in_chunks(connection, wanted)
            for row in connection.execute(query.where(id_in(connection, table.c.asset_id, chunk)))
        ]


def _picture(
    row: Mapping[str, Any],
    taken_at: datetime,
    fact: StoredAssetAnnotationFacts,
    canonical: Mapping[str, str],
) -> LibraryPicture:
    heads = dict(fact.heads)
    return LibraryPicture(
        asset_id=row["asset_id"],
        taken_at=taken_at,
        media_kind=row["media_kind"] or "photo",
        caption=fact.description,
        city=row["city"] or None,
        region=row["state"] or None,
        country=row["country"] or None,
        latitude=row["latitude"],
        longitude=row["longitude"],
        picture_kind=heads.get("doc_docling"),
        sharpness=fact.pixel.sharpness if fact.pixel else None,
        people=frozenset(
            canonical[person.person_id] for person in fact.people if person.person_id in canonical
        ),
    )
