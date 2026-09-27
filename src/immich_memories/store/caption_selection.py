"""Reuse a complete SmolVLM caption before an explicitly chosen LLM's description."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from immich_memories.analysis.editorial_description_contract import (
    DESCRIPTION_MODEL,
    DESCRIPTION_SOURCE,
    DescriptionEnvelope,
    validate_envelope,
)
from immich_memories.analysis.llm_caption_identity import LLM_DESCRIPTION_SOURCE
from immich_memories.db import Store
from immich_memories.db.tables import description_fields, description_unavailable, descriptions
from immich_memories.store.batches import id_in, in_chunks


@dataclass(frozen=True)
class SelectedCaption:
    model: str
    envelope: DescriptionEnvelope


def selected_captions(
    connection: Connection, asset_ids: Sequence[str], model: str
) -> dict[str, SelectedCaption]:
    """Choose one complete row pair per picture; never mix fields between producers."""
    wanted = list(dict.fromkeys(asset_ids))
    return _complete_rows(connection, wanted, model, LLM_DESCRIPTION_SOURCE) | _complete_rows(
        connection, wanted, DESCRIPTION_MODEL, DESCRIPTION_SOURCE
    )


def _complete_rows(
    connection: Connection, wanted: Sequence[str], model: str, source: str
) -> dict[str, SelectedCaption]:
    d, f = descriptions, description_fields
    texts: dict[str, Any] = {}
    fields: dict[str, dict[str, Any]] = {}
    for chunk in in_chunks(connection, wanted):
        rows = connection.execute(
            sa.select(d.c.asset_id, d.c.text, f.c.field, f.c.value)
            .select_from(
                d.outerjoin(f, sa.and_(d.c.asset_id == f.c.asset_id, d.c.model == f.c.model))
            )
            .where(d.c.model == model, d.c.source == source, id_in(connection, d.c.asset_id, chunk))
        )
        for asset_id, text, field, value in rows:
            texts[str(asset_id)] = text
            fields.setdefault(str(asset_id), {})[str(field)] = value
    selected = {}
    for asset_id, text in texts.items():
        if set(fields[asset_id]) != {"setting"}:
            continue
        try:
            envelope = validate_envelope({"description": text} | fields[asset_id])
        except (TypeError, ValueError):
            continue
        selected[asset_id] = SelectedCaption(model, envelope)
    return selected


def conflicting_caption_ids(store: Store, asset_ids: Sequence[str], model: str) -> set[str]:
    """Refuse partial or terminal rows before paying for a caption that cannot be inserted."""
    wanted = list(dict.fromkeys(asset_ids))
    touched: set[str] = set()
    with store.connect() as connection:
        for chunk in in_chunks(connection, wanted):
            for table in (descriptions, description_fields, description_unavailable):
                touched.update(
                    connection.execute(
                        sa.select(table.c.asset_id).where(
                            table.c.model == model, id_in(connection, table.c.asset_id, chunk)
                        )
                    ).scalars()
                )
    return touched
