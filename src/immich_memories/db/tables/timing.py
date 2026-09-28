"""Buffered observations saved with a run, removed when that run is deleted."""

from sqlalchemy import JSON, Column, ForeignKey, Integer, String, Table

from immich_memories.db.metadata import metadata
from immich_memories.db.tables.operations import pipeline_runs

run_spans = Table(
    "run_spans",
    metadata,
    Column(
        "run_id", String(), ForeignKey(pipeline_runs.c.run_id, ondelete="CASCADE"), primary_key=True
    ),
    Column("span_id", Integer(), primary_key=True),
    Column("record", JSON(), nullable=False),
)

run_diagnostics = Table(
    "run_diagnostics",
    metadata,
    Column(
        "run_id", String(), ForeignKey(pipeline_runs.c.run_id, ondelete="CASCADE"), primary_key=True
    ),
    Column("record", JSON(), nullable=False),
)
