"""Reuse a complete SmolVLM caption before an explicitly chosen LLM's description."""

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

from immich_memories.analysis.editorial_description_contract import (
    DESCRIPTION_MODEL,
    DESCRIPTION_SOURCE,
    DescriptionEnvelope,
    validate_envelope,
)
from immich_memories.analysis.llm_caption_identity import LLM_DESCRIPTION_SOURCE


@dataclass(frozen=True)
class SelectedCaption:
    model: str
    envelope: DescriptionEnvelope


def selected_captions(
    connection: sqlite3.Connection, asset_ids: Sequence[str], model: str
) -> dict[str, SelectedCaption]:
    """Choose one complete row pair per picture; never mix fields between producers."""
    connection.execute(
        "CREATE TEMP TABLE IF NOT EXISTS _caption_wanted (asset_id TEXT PRIMARY KEY)"
    )
    connection.execute("DELETE FROM _caption_wanted")
    connection.executemany(
        "INSERT OR IGNORE INTO _caption_wanted VALUES (?)", ((a,) for a in asset_ids)
    )
    return _complete_rows(connection, model, LLM_DESCRIPTION_SOURCE) | _complete_rows(
        connection, DESCRIPTION_MODEL, DESCRIPTION_SOURCE
    )


def _complete_rows(
    connection: sqlite3.Connection, model: str, source: str
) -> dict[str, SelectedCaption]:
    rows = connection.execute(
        "SELECT d.asset_id,d.text,f.field,f.value FROM _caption_wanted w "
        "CROSS JOIN descriptions d ON d.asset_id=w.asset_id "
        "LEFT JOIN description_fields f ON d.asset_id=f.asset_id AND d.model=f.model "
        "WHERE d.model=? AND d.source=?",
        (model, source),
    )
    texts: dict[str, str] = {}
    fields: dict[str, dict[str, str]] = {}
    for asset_id, text, field, value in rows:
        texts[asset_id] = text
        fields.setdefault(asset_id, {})[field] = value
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


def conflicting_caption_rows(connection: sqlite3.Connection, asset_id: str, model: str) -> bool:
    """Refuse partial or terminal rows before paying for a caption that cannot be inserted."""
    touched = connection.execute(
        "SELECT 1 FROM descriptions WHERE asset_id=? AND model=? UNION ALL "
        "SELECT 1 FROM description_fields WHERE asset_id=? AND model=?",
        (asset_id, model, asset_id, model),
    ).fetchone()
    outcome_table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='description_unavailable'"
    ).fetchone()
    stale = (
        outcome_table
        and connection.execute(
            "SELECT 1 FROM description_unavailable WHERE asset_id=? AND model=?",
            (asset_id, model),
        ).fetchone()
    )
    return bool(touched or stale)
