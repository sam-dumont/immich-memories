"""Which title prompt a memory gets.

A film about people is named from the family record; an occasion from what
the occasion was. Everything else is a trip, which also classifies its route.
"""

from __future__ import annotations

PEOPLE_MEMORY_TYPES = frozenset({"person_spotlight", "multi_person"})
OCCASION_MEMORY_TYPES = frozenset(
    {
        "album",
        "holiday",
        "monthly_highlights",
        "on_this_day",
        "season",
        "special_day",
        "year",
        "year_in_review",
    }
)


def is_trip(memory_type: str) -> bool:
    """Whether this memory is named by the trip prompt, which also classifies the route."""
    return memory_type not in PEOPLE_MEMORY_TYPES and memory_type not in OCCASION_MEMORY_TYPES
