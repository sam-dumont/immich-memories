"""What a reverse geocoder said about a place, kept so a library is asked about once.

One row per coordinate cell (two decimals, about a kilometre) and answer language. The
address holds only the administrative names (district, town, region, country), never a
street: that is all a film names, and all the cache needs to keep.
"""

from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, String, Table

from immich_memories.db.metadata import metadata

geocoded_places = Table(
    "geocoded_places",
    metadata,
    Column("cell", String(), primary_key=True),
    Column("language", String(), primary_key=True),
    # Empty when the geocoder knew nothing there (open sea), so it is not asked again.
    Column("address", JSON, nullable=False),
    Column("fetched_at", DateTime, nullable=False),
)
