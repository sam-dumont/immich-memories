"""Asset-level scores (videos and photos): model answers someone paid for, kept in the store.

Separated from VideoAnalysisCache for cohesion: this handles pre-filtering scores while
VideoAnalysisCache handles per-segment analysis results, which stay derived cache.
"""

from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa

from immich_memories.db import Store, iso_from_db, now_db, open_store, upsert
from immich_memories.db.tables import asset_scores

logger = logging.getLogger(__name__)

_SCORES = asset_scores.c


class AssetScoreCache:
    """Banked asset scores, one per asset per prompt version."""

    def __init__(self, store: Store | None = None):
        self.store = store or open_store()

    def save_asset_score(
        self,
        asset_id: str,
        asset_type: str,
        metadata_score: float,
        combined_score: float,
        llm_interest: float | None = None,
        llm_quality: float | None = None,
        llm_emotion: str | None = None,
        llm_description: str | None = None,
        llm_category: str | None = None,
        model_version: str | None = None,
    ) -> None:
        """Bank a look under its version, replacing only that version's answer.

        A save under a new version leaves what earlier versions said in place —
        a prompt edit re-asks the model, it does not throw the corpus away.
        Rows saved without a version share the one empty-string version, which
        is what the pre-versioning rows migrate onto.
        """
        row = {
            "asset_id": asset_id,
            "model_version": model_version or "",
            "asset_type": asset_type,
            "metadata_score": metadata_score,
            "combined_score": combined_score,
            "llm_interest": llm_interest,
            "llm_quality": llm_quality,
            "llm_emotion": llm_emotion,
            "llm_description": llm_description,
            "llm_category": llm_category,
            "analyzed_at": now_db(),
        }
        with self.store.begin() as conn:
            upsert(conn, asset_scores, [row], ["asset_id", "model_version"])

    def all_scores(self) -> list[dict[str, Any]]:
        """Every banked look, oldest first, as plain rows (`analyzed_at` as ISO text)."""
        with self.store.connect() as conn:
            rows = conn.execute(
                sa.select(asset_scores).order_by(
                    _SCORES.analyzed_at, _SCORES.asset_id, _SCORES.model_version
                )
            ).mappings()
            return [dict(row) | {"analyzed_at": iso_from_db(row["analyzed_at"])} for row in rows]

    def get_cache_stats(self) -> dict:
        """Statistics for the `cache stats` CLI command.

        `total` counts banked looks and `assets` counts the assets they are
        about — the two differ once a prompt version bump leaves an asset
        holding an answer from each version, which is the point of doing so.
        """
        with self.store.connect() as conn:
            totals = conn.execute(
                sa.select(
                    sa.func.count().label("total"),
                    sa.func.count(sa.distinct(_SCORES.asset_id)).label("assets"),
                    sa.func.min(_SCORES.analyzed_at).label("oldest"),
                    sa.func.max(_SCORES.analyzed_at).label("newest"),
                    sa.func.count().filter(_SCORES.llm_interest.is_not(None)).label("with_llm"),
                )
            ).one()
            by_type = conn.execute(
                sa.select(_SCORES.asset_type, sa.func.count().label("looks")).group_by(
                    _SCORES.asset_type
                )
            ).all()
        return {
            "total": totals.total,
            "assets": totals.assets,
            "by_type": {row.asset_type: row.looks for row in by_type},
            "with_llm": totals.with_llm,
            "oldest": iso_from_db(totals.oldest),
            "newest": iso_from_db(totals.newest),
        }
