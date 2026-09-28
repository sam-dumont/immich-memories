"""One persistence boundary for timings, diagnostics and progress history."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from immich_memories.db import Store
from immich_memories.db.tables import pipeline_runs, run_diagnostics, run_spans
from immich_memories.tracking.timing import Collector, Span


class SpanStore:
    def __init__(self, store: Store) -> None:
        self.store = store

    def save(self, run_id: str, collected: Collector, **diagnostics: Any) -> None:
        """Replace one run's snapshot atomically; never write inside a measured span."""
        with self.store.begin() as conn:
            for table in (run_spans, run_diagnostics):
                conn.execute(sa.delete(table).where(table.c.run_id == run_id))
            if collected.spans:
                conn.execute(
                    sa.insert(run_spans),
                    [
                        {"run_id": run_id, "span_id": span.span_id, "record": span.to_dict()}
                        for span in collected.spans
                    ],
                )
            conn.execute(
                sa.insert(run_diagnostics),
                [
                    {
                        "run_id": run_id,
                        "record": diagnostics | {"logs": collected.logs},
                    }
                ],
            )

    def load(self, run_id: str) -> Collector:
        """Reconstruct the exportable buffer without starting a timing context."""
        with self.store.connect() as conn:
            rows: sa.ScalarResult[dict[str, Any]] = conn.execute(
                sa.select(run_spans.c.record)
                .where(run_spans.c.run_id == run_id)
                .order_by(run_spans.c.span_id)
            ).scalars()
            spans = [Span(**row) for row in rows]
        return Collector(spans=spans, logs=self.diagnostics(run_id).get("logs", []))

    def diagnostics(self, run_id: str) -> dict[str, Any]:
        """Return private observations for the allowlisted report builder."""
        with self.store.connect() as conn:
            return (
                conn.execute(
                    sa.select(run_diagnostics.c.record).where(run_diagnostics.c.run_id == run_id)
                ).scalar()
                or {}
            )

    def latest(self, source: str, *, prefix: str = "") -> Collector | None:
        """Use only completed runs with measured work as progress references."""
        with self.store.connect() as conn:
            run_id = conn.execute(
                sa.select(pipeline_runs.c.run_id)
                .where(
                    pipeline_runs.c.status == "completed",
                    pipeline_runs.c.source == source,
                    sa.exists().where(
                        run_spans.c.run_id == pipeline_runs.c.run_id,
                        run_spans.c.record["name"].as_string().startswith(prefix),
                    ),
                )
                .order_by(pipeline_runs.c.completed_at.desc())
                .limit(1)
            ).scalar()
        return self.load(run_id) if run_id else None
