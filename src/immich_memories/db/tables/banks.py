"""Answers a film paid for and decisions its owner made, kept across films.

Formerly JSON files under `structure-banks/` (the audience bank, the memory-worthy and
thesis-fit vote banks) and one `<film>.owner-edits-<id>.private.json` beside each reviewed
film. Values stay JSON: each is one answer or one decision, read and written whole.
"""

from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, Table, Text

from immich_memories.db.metadata import metadata

# One model's audience answer, by who answered and the evidence key it answered.
audience_answers = Table(
    "audience_answers",
    metadata,
    Column("answerer", Text, primary_key=True),
    Column("evidence_key", Text, primary_key=True),
    Column("record", JSON, nullable=False),
)

# A picture's audience hold, one row per slot: `permanent` (a detector or a rule) or `text`
# (a model reading text, stamped with the prompt it answered).
audience_holds = Table(
    "audience_holds",
    metadata,
    Column("asset_id", Text, primary_key=True),
    Column("slot", Text, primary_key=True),
    Column("hold", JSON, nullable=False),
)

# One entry of a two-order block vote bank: `section` is empty for a block's answer, or
# `rows` / `rows-one-order` for one row's banked vote. `scope` is the film's case key.
vote_bank_entries = Table(
    "vote_bank_entries",
    metadata,
    Column("bank", Text, primary_key=True),
    Column("scope", Text, primary_key=True),
    Column("section", Text, primary_key=True),
    Column("entry_key", Text, primary_key=True),
    Column("value", JSON, nullable=False),
)

# What the owner changed in review before a render: removals, trims, timing.
owner_edits = Table(
    "owner_edits",
    metadata,
    Column("edit_id", Text, primary_key=True),
    Column("film_stem", Text, nullable=False),
    Column("attempt_id", Text, nullable=True, index=True),
    Column("record", JSON, nullable=False),
    Column("recorded_at", DateTime, nullable=False),
)
