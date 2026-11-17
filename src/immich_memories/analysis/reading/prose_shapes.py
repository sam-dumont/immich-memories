"""The JSON shape each prose seat asks the server for (response_format json_schema).

The shape repeats what the seat's own parser accepts, no more: a server that honours it can
only write an answer the parser reads, so a small model never loses a whole pack to one
broken token. The parsers still check everything; the shape is never trusted on its own.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from immich_memories.analysis.reading.cull_answer import CULL_BUCKETS

TRIP_TYPES = ("multi_base", "base_camp", "road_trip", "hiking_trail")
MAP_MODES = ("title_only", "excursions", "overnight_stops")


def _named(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": True}}


def _object(properties: dict[str, Any], required: Sequence[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties if required is None else required),
        "additionalProperties": False,
    }


def episode_reading_shape(pictures: int, *, lean: bool) -> dict[str, Any]:
    """One episode's reading, its rows naming pictures 1 to `pictures`; the lean question asks
    no Cull."""
    number = {"type": "integer", "minimum": 1, "maximum": max(1, pictures)}
    row = _object({"picture": number, "reason": {"type": "string"}})
    reading: dict[str, Any] = {
        "what_happened": {"type": "string"},
        "representatives": {"type": "array", "items": row, "minItems": 1, "maxItems": 3},
        "notable_moments": {"type": "array", "items": row},
    }
    if not lean:
        bucket = _object({"picture": number, "bucket": {"enum": list(CULL_BUCKETS)}})
        reading["cull"] = {"type": "array", "items": bucket}
    return _named("episode_reading", _object(reading))


def accounts_shape(keys: Sequence[str], *, max_chars: int) -> dict[str, Any]:
    """An account for every offered key, and no other key."""
    notes = {key: {"type": "string", "maxLength": max_chars} for key in keys}
    return _named("accounts", _object({"accounts": _object(notes)}))


def title_shape(*, trip: bool) -> dict[str, Any]:
    """The fields the title prompt asks for; a trip's also classifies its travel pattern."""
    fields: dict[str, Any] = {"title": {"type": "string"}, "subtitle": {"type": ["string", "null"]}}
    if trip:
        fields |= {
            "trip_type": {"enum": [*TRIP_TYPES, None]},
            "map_mode": {"enum": [*MAP_MODES, None]},
            "map_mode_reason": {"type": ["string", "null"]},
        }
    else:
        fields["reason"] = {"type": "string"}
    return _named("title", _object(fields))
