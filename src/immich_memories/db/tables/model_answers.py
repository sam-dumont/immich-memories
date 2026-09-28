"""Answers a model gave about a set of pictures, keyed by exactly what it was asked.

Judgments by prompt hash, Cull verdicts by pass version, episode readings by membership and
producer, library overviews by node. Formerly spread over `annotations.sqlite`,
`judgments.db` and a `text-judgments.sqlite` beside an attempt.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Table, Text

from immich_memories.db.metadata import metadata

judgments = Table(
    "judgments",
    metadata,
    Column("key", Text, primary_key=True),
    Column("answer", Text, nullable=False),
    # Indexed so a process can ask only for the questions answered since it last looked.
    Column("answered_at", DateTime, nullable=False, index=True),
)

text_completion_failures = Table(
    "text_completion_failures",
    metadata,
    Column("key", Text, primary_key=True),
    Column("record", Text, nullable=False),
    Column("recorded_at", DateTime, nullable=False),
)

editorial_verdicts = Table(
    "editorial_verdicts",
    metadata,
    Column("asset_id", Text, primary_key=True),
    Column("pass_version", Text, primary_key=True),
    Column("bucket", Text, nullable=False),
    Column("decided_at", DateTime, nullable=False),
)

editorial_episode_readings = Table(
    "editorial_episode_readings",
    metadata,
    Column("group_id", Text, primary_key=True),
    Column("producer_key", Text, primary_key=True),
    Column("evidence_key", Text, primary_key=True),
    Column("full_asset_ids", Text, nullable=False),
    Column("what_happened", Text, nullable=False),
    Column("representatives", Text, nullable=False),
    Column("cull_decisions", Text, nullable=False),
    Column("notable_moments", Text, nullable=False),
    Column("answered_at", DateTime, nullable=False),
)

editorial_episode_refusals = Table(
    "editorial_episode_refusals",
    metadata,
    Column("group_id", Text, primary_key=True),
    Column("producer_key", Text, primary_key=True),
    Column("evidence_key", Text, primary_key=True),
    Column("reason", Text, nullable=False),
    Column("answered_at", DateTime, nullable=False),
)

library_overviews = Table(
    "library_overviews",
    metadata,
    Column("node_key", Text, primary_key=True),
    Column("kind", Text, nullable=False),
    Column("period", Text, nullable=False),
    Column("account", Text, nullable=False),
    Column("children", Text, nullable=False),
)
