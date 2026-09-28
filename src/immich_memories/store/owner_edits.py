"""What the owner changed when reviewing a cut before rendering it: kept whole, as decided.

One row per reviewed render: the record `project_editorial_owner_edits` built (removals,
trims, a changed timing policy), the film it went into, and the attempt whose cut was reviewed.
The record goes in and comes back exactly as given.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import sqlalchemy as sa

from immich_memories.db import Store, now_db
from immich_memories.db.tables import owner_edits


def keep_owner_edits(
    store: Store, record: dict[str, Any], *, film: Path, attempt: Path | None
) -> None:
    """Bank one review's edits under the record's `edit_id`.

    `attempt` is the directory of the cut that was reviewed; `runs why` finds the edits by
    its name.
    """
    with store.begin() as connection:
        connection.execute(
            sa.insert(owner_edits).values(
                edit_id=record["edit_id"],
                film_stem=film.stem,
                attempt_id=Path(attempt).name if attempt is not None else None,
                record=record,
                recorded_at=now_db(),
            )
        )


def owner_edits_of_attempt(store: Store, attempt_id: str) -> list[dict[str, Any]]:
    """Every review edit made to this attempt's cut, oldest first."""
    with store.connect() as connection:
        return list(
            connection.execute(
                sa.select(owner_edits.c.record)
                .where(owner_edits.c.attempt_id == attempt_id)
                .order_by(owner_edits.c.recorded_at, owner_edits.c.edit_id)
            ).scalars()
        )
