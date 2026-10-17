"""Memory parameters as JSON that gives dates and instants back as dates and instants.

A run's preset parameters hold `date` and `datetime` values (a special day, its window and
run, a trip's bounds) that plain `json` refuses. Both the saved cut and the render worker's
request carry them, so both use this one tagging.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

_DATETIME = "__datetime__"
_DATE = "__date__"


def encode_dated(value: Any) -> Any:
    """``value`` as plain JSON, each date and datetime tagged so `decode_dated` restores it.

    Tuples become lists, and anything else JSON has no type for becomes its text.
    """
    if isinstance(value, datetime):
        return {_DATETIME: value.isoformat()}
    if isinstance(value, date):
        return {_DATE: value.isoformat()}
    if isinstance(value, Mapping):
        return {str(k): encode_dated(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode_dated(v) for v in value]
    return value if value is None or isinstance(value, (str, int, float, bool)) else str(value)


def decode_dated(value: Any) -> Any:
    """The value `encode_dated` was given, its dates and datetimes restored."""
    if isinstance(value, dict):
        if set(value) == {_DATETIME}:
            return datetime.fromisoformat(value[_DATETIME])
        if set(value) == {_DATE}:
            return date.fromisoformat(value[_DATE])
        return {k: decode_dated(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decode_dated(v) for v in value]
    return value
