"""The people registry: who is in the library, and what the owner confirmed about them.

One row per person keyed by the canonical id (the first id the person was known by, an
Immich person id or a `manual:` id), every id the person answers to, and the confirmed
relationships as rows. What a scan recomputes (`inferred`) and the rest of a person's
record stay JSON: the scan owns that shape and rewrites it whole.
"""

from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Table, Text

from immich_memories.db.metadata import metadata

# One row per registry. Its header holds the document's own top-level facts (version,
# generated, owner), and every writer locks this row first, so a scan and a confirmation
# from two processes queue instead of dropping each other's change.
people_registry = Table(
    "people_registry",
    metadata,
    Column("registry", String(64), primary_key=True),
    Column("header", JSON, nullable=True),
    Column("updated_at", DateTime, nullable=True),
)

people = Table(
    "people",
    metadata,
    Column("person_id", String(255), primary_key=True),
    Column("position", Integer, nullable=False),
    Column("name", Text, nullable=True),
    Column("birth_date", String(32), nullable=True),
    Column("origin", String(32), nullable=True),
    Column("inferred", JSON, nullable=True),
    # The confirmed block without its links, which live in people_relationships.
    Column("confirmed", JSON, nullable=True),
    # Any other key a hand edit put on the person, carried through verbatim.
    Column("extra", JSON, nullable=True),
)

# Every id a person answers to, the canonical one at position 0. An id belongs to one person.
people_aliases = Table(
    "people_aliases",
    metadata,
    Column("alias_id", String(255), primary_key=True),
    Column(
        "person_id",
        String(255),
        ForeignKey(people.c.person_id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("position", Integer, nullable=False),
)

# The confirmed links, in the order the person's block lists them. `target_id` is not a
# foreign key: a link to somebody who left the roster is still the owner's answer.
people_relationships = Table(
    "people_relationships",
    metadata,
    Column(
        "person_id",
        String(255),
        ForeignKey(people.c.person_id, ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("position", Integer, primary_key=True),
    Column("kind", String(64), nullable=True),
    Column("target_id", String(255), nullable=True, index=True),
    Column("reverse", String(64), nullable=True),
    Column("decision", String(32), nullable=True),
    Column("extra", JSON, nullable=True),
)
