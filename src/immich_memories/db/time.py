"""Instants in the store are naive UTC; the repository edge converts them.

`DateTime` without a timezone is the one type that stores the same value on SQLite (text) and
PostgreSQL (`timestamp`). So everything goes in as UTC with the zone stripped, and comes back
out as an aware UTC datetime. A naive value handed in is taken to be UTC already.
"""

from __future__ import annotations

from datetime import UTC, datetime


def to_db(value: datetime | str | None) -> datetime | None:
    """An aware datetime, a naive UTC one, or an ISO-8601 string, as naive UTC."""
    if value is None:
        return None
    instant = datetime.fromisoformat(value) if isinstance(value, str) else value
    if instant.tzinfo is not None:
        instant = instant.astimezone(UTC).replace(tzinfo=None)
    return instant


def from_db(value: datetime | None) -> datetime | None:
    """A stored naive-UTC datetime as an aware UTC one."""
    return None if value is None else value.replace(tzinfo=UTC)


def iso_from_db(value: datetime | None) -> str | None:
    """A stored datetime as an ISO-8601 string with `+00:00`."""
    instant = from_db(value)
    return None if instant is None else instant.isoformat()


def now_db() -> datetime:
    """This instant, as the store keeps it."""
    return datetime.now(UTC).replace(tzinfo=None)
