"""Persist source metadata and exact-producer annotation preparation facts."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from immich_memories.analysis.editorial_description_contract import (
    DESCRIPTION_MODEL,
    DESCRIPTION_SOURCE,
    validate_envelope,
)
from immich_memories.analysis.editorial_description_outcomes import unavailable_for
from immich_memories.analysis.llm_caption_identity import LLM_CAPTION_PREFIX
from immich_memories.analysis.subject_framing import FaceBox
from immich_memories.api.models import Asset
from immich_memories.db import Store, now_db, to_db
from immich_memories.db.tables import (
    annotation_assets,
    asset_people,
    description_fields,
    descriptions,
    face_boxes,
    face_reads,
    head_facts,
    pixel_facts,
    pixel_facts_thresholds,
)
from immich_memories.store.batches import bank_rows, id_in, in_chunks, insert_rows, upsert_rows
from immich_memories.store.caption_selection import selected_captions


def now() -> str:
    """This instant as ISO text, for evidence that is itself text (a flag's JSON, a report)."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def remember_assets(store: Store, assets: Sequence[Asset]) -> None:
    """Use already fetched Immich metadata; never derive flags from captions."""
    rows = [_asset_row(asset) for asset in assets]
    people = [row for asset in assets for row in _people_rows(asset, now_db())]
    ids = [row["asset_id"] for row in rows]
    with store.begin() as connection:
        upsert_rows(connection, annotation_assets, rows, keys=("asset_id",))
        # Current source metadata is authoritative for people; owner flags remain untouched.
        for chunk in in_chunks(connection, ids):
            connection.execute(
                sa.delete(asset_people).where(id_in(connection, asset_people.c.asset_id, chunk))
            )
        # Two people sharing a name in one picture keep one row, the last, as the file did.
        upsert_rows(connection, asset_people, people, keys=("asset_id", "person_name"))


def _asset_row(asset: Asset) -> dict[str, Any]:
    exif = asset.exif_info
    taken = (
        (exif.date_time_original if exif else None)
        or asset.local_date_time
        or asset.file_created_at
    )
    return {
        "asset_id": asset.id,
        "taken_at": to_db(taken),
        "media_kind": "video" if asset.is_video else "photo",
        "favourite": asset.is_favorite,
        "original_file": asset.original_file_name,
        "width": asset.width,
        "height": asset.height,
        **{
            key: getattr(exif, key, None)
            for key in ("city", "state", "country", "latitude", "longitude")
        },
        "live_photo_video_id": asset.live_photo_video_id,
        "duration_seconds": asset.duration_seconds,
    }


def _people_rows(asset: Asset, timestamp: datetime) -> list[dict[str, Any]]:
    return [
        {
            "asset_id": asset.id,
            "person_name": person.name,
            "person_id": person.id,
            "birth_date": person.birth_date.date().isoformat() if person.birth_date else None,
            "written_at": timestamp,
        }
        for person in asset.people
        if person.name.strip()
    ]


FACE_PRODUCER = "immich-faces-v2"


def remember_faces(store: Store, boxes: Mapping[str, Sequence[FaceBox]]) -> None:
    """Bank a batch of pictures' face geometry; a picture with no face is banked as read.

    Each box keeps the Immich person id matched to it, never the name: a memory
    about one person has to find that person's face among the other named ones.
    """
    if not boxes:
        return
    ids = list(boxes)
    read_at = now_db()
    rows = [
        {
            "asset_id": asset_id,
            "ordinal": ordinal,
            "named": b.named,
            "x1": b.x1,
            "y1": b.y1,
            "x2": b.x2,
            "y2": b.y2,
            "person_id": b.person_id,
        }
        for asset_id, found in boxes.items()
        for ordinal, b in enumerate(found)
    ]
    with store.begin() as connection:
        for chunk in in_chunks(connection, ids):
            connection.execute(
                sa.delete(face_boxes).where(id_in(connection, face_boxes.c.asset_id, chunk))
            )
        if rows:
            insert_rows(connection, face_boxes, rows)
        upsert_rows(
            connection,
            face_reads,
            [{"asset_id": a, "producer": FACE_PRODUCER, "read_at": read_at} for a in ids],
            keys=("asset_id", "producer"),
        )


def remember_head_rows(store: Store, rows: Sequence[Mapping[str, object]]) -> None:
    """Bank decided head rows as a producer wrote them; a later row for a key replaces it."""
    latest = {
        (row["asset_id"], row["head"], row["version"]): {
            **row,
            "decided_at": to_db(str(row["decided_at"])) if row.get("decided_at") else None,
        }
        for row in rows
    }
    if latest:
        with store.begin() as connection:
            upsert_rows(
                connection, head_facts, list(latest.values()), keys=("asset_id", "head", "version")
            )


def faces_unread(store: Store, asset_ids: Sequence[str]) -> tuple[str, ...]:
    """The wanted pictures no face read has covered yet, in the caller's order."""
    wanted = list(dict.fromkeys(asset_ids))
    read: set[str] = set()
    with store.connect() as connection:
        for chunk in in_chunks(connection, wanted):
            found: list[Any] = list(
                connection.execute(
                    sa.select(face_reads.c.asset_id).where(
                        face_reads.c.producer == FACE_PRODUCER,
                        id_in(connection, face_reads.c.asset_id, chunk),
                    )
                ).scalars()
            )
            read.update(str(asset_id) for asset_id in found)
    return tuple(asset_id for asset_id in asset_ids if asset_id not in read)


def missing_facts(
    store: Store,
    asset_ids: Sequence[str],
    *,
    description_model: str,
    head_versions: Mapping[str, str],
    pixel_producer_key: str,
    preview_for: Callable[[str], bytes],
) -> tuple[dict[str, tuple[str, ...]], tuple[str, ...]]:
    """Report all missing or malformed producers, plus proven terminal caption failures."""
    wanted = tuple(dict.fromkeys(asset_ids))
    with store.connect() as connection:
        complete = (
            set(selected_captions(connection, wanted, description_model))
            if description_model.startswith(LLM_CAPTION_PREFIX)
            else _complete_captions(connection, wanted, description_model)
        )
        unavailable: set[str] = set()
        if description_model == DESCRIPTION_MODEL:
            unavailable, damaged = _terminal_caption_failures(connection, wanted, preview_for)
            complete -= damaged
        missing: dict[str, tuple[str, ...]] = {
            f"description:{description_model}": tuple(
                a for a in wanted if a not in complete | unavailable
            )
        }
        for head, version in head_versions.items():
            found = _decided_heads(connection, wanted, head, version)
            missing[f"head:{head}@{version}"] = tuple(a for a in wanted if a not in found)
        pixels = _measured_pixels(connection, wanted, pixel_producer_key)
    missing[f"pixel:{pixel_producer_key}"] = tuple(a for a in wanted if a not in pixels)
    return {key: ids for key, ids in missing.items() if ids}, tuple(
        a for a in wanted if a in unavailable
    )


def _complete_caption(
    description_model: str, text: Any, source: Any, fields: Mapping[str, Any]
) -> bool:
    if description_model != DESCRIPTION_MODEL:
        return bool(text) and bool(fields.get("setting"))
    if source != DESCRIPTION_SOURCE or set(fields) != {"setting"}:
        return False
    try:
        validate_envelope({"description": text, "setting": fields["setting"]})
    except (TypeError, ValueError):
        return False
    return True


def _complete_captions(
    connection: Connection, wanted: Sequence[str], description_model: str
) -> set[str]:
    texts: dict[str, tuple[Any, Any]] = {}
    fields: dict[str, dict[str, Any]] = {}
    for chunk in in_chunks(connection, wanted):
        texts.update(
            (row.asset_id, (row.text, row.source))
            for row in connection.execute(
                sa.select(
                    descriptions.c.asset_id, descriptions.c.text, descriptions.c.source
                ).where(
                    descriptions.c.model == description_model,
                    id_in(connection, descriptions.c.asset_id, chunk),
                )
            )
        )
        for asset_id, field, value in connection.execute(
            sa.select(
                description_fields.c.asset_id,
                description_fields.c.field,
                description_fields.c.value,
            ).where(
                description_fields.c.model == description_model,
                id_in(connection, description_fields.c.asset_id, chunk),
            )
        ):
            fields.setdefault(str(asset_id), {})[str(field)] = value
    return {
        asset_id
        for asset_id, (text, source) in texts.items()
        if _complete_caption(description_model, text, source, fields.get(asset_id, {}))
    }


def _terminal_caption_failures(
    connection: Connection,
    wanted: Sequence[str],
    preview_for: Callable[[str], bytes],
) -> tuple[set[str], set[str]]:
    """Only a damaged batch needs isolated reads. Conflicting evidence cannot be complete."""
    with suppress(OSError, ValueError, SQLAlchemyError):
        return set(unavailable_for(connection, wanted, preview_for=preview_for)), set()
    unavailable: set[str] = set()
    damaged: set[str] = set()
    for asset_id in wanted:
        try:
            unavailable.update(unavailable_for(connection, (asset_id,), preview_for=preview_for))
        except (OSError, ValueError, SQLAlchemyError):
            damaged.add(asset_id)
    return unavailable, damaged


def heads_missing_for(
    store: Store, asset_ids: Sequence[str], head: str, version: str
) -> tuple[str, ...]:
    """Which of these sources one head has not decided yet, in the caller's order.

    Separate from :func:`missing_facts` because it asks about one producer over sources
    that are not candidates: an attached clip owes the exposure head a row and owes no
    caption, no context head and no pixel fact.
    """
    wanted = tuple(dict.fromkeys(asset_ids))
    if not wanted:
        return ()
    with store.connect() as connection:
        decided = _decided_heads(connection, wanted, head, version)
    return tuple(asset_id for asset_id in wanted if asset_id not in decided)


def carry_head_answers(
    store: Store,
    asset_ids: Sequence[str],
    head: str,
    *,
    banked_version: str,
    version: str,
    encoder_key: str,
) -> None:
    """Bank each source's ``banked_version`` answer under ``version`` where it has none yet.

    For a producer whose new version computes exactly what the old one did for these
    sources; the caller names the sources, the store only copies. Only a decided row the
    same producer (``encoder_key``) wrote is carried, keeping the time it was decided, and
    a source already decided under ``version`` keeps its own row.
    """
    h = head_facts
    carried: list[dict[str, Any]] = []
    with store.connect() as connection:
        decided = _decided_heads(connection, asset_ids, head, version)
        for chunk in in_chunks(connection, [a for a in asset_ids if a not in decided]):
            carried.extend(
                {**row._mapping, "version": version}
                for row in connection.execute(
                    sa.select(h).where(
                        h.c.head == head,
                        h.c.version == banked_version,
                        h.c.encoder_key == encoder_key,
                        id_in(connection, h.c.asset_id, chunk),
                    )
                )
                if _is_decided(row.label, row.confidence)
            )
    bank_rows(store, h, carried, keys=("asset_id", "head", "version"))


def _decided_heads(
    connection: Connection, wanted: Sequence[str], head: str, version: str
) -> set[str]:
    decided: set[str] = set()
    for chunk in in_chunks(connection, wanted):
        decided.update(
            str(asset_id)
            for asset_id, label, confidence in connection.execute(
                sa.select(head_facts.c.asset_id, head_facts.c.label, head_facts.c.confidence).where(
                    head_facts.c.head == head,
                    head_facts.c.version == version,
                    id_in(connection, head_facts.c.asset_id, chunk),
                )
            )
            if _is_decided(label, confidence)
        )
    return decided


def _is_decided(label: Any, confidence: Any) -> bool:
    return (
        isinstance(label, str)
        and bool(label.strip())
        and isinstance(confidence, (int, float))
        and math.isfinite(confidence)
        and 0 <= confidence <= 1
    )


_PIXEL_VALUES = ("sharpness", "brightness", "contrast", "dark_fraction", "bright_fraction")


def _measured_pixels(
    connection: Connection, wanted: Sequence[str], pixel_producer_key: str
) -> set[str]:
    threshold = connection.execute(
        sa.select(pixel_facts_thresholds.c.value).where(
            pixel_facts_thresholds.c.name == "sharpness_p10",
            pixel_facts_thresholds.c.producer_key == pixel_producer_key,
        )
    ).first()
    if (
        threshold is None
        or not isinstance(threshold[0], (float, int))
        or not math.isfinite(threshold[0])
    ):
        return set()
    columns = [pixel_facts.c[name] for name in _PIXEL_VALUES]
    pixels: set[str] = set()
    for chunk in in_chunks(connection, wanted):
        pixels.update(
            str(asset_id)
            for asset_id, *values in connection.execute(
                sa.select(pixel_facts.c.asset_id, *columns).where(
                    pixel_facts.c.producer_key == pixel_producer_key,
                    id_in(connection, pixel_facts.c.asset_id, chunk),
                )
            )
            if all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)
        )
    return pixels
