"""What a special day's film is called and how it is cut up, whichever surface asked for it."""

from __future__ import annotations

from datetime import date

from immich_memories.filename_builder import get_divider_mode
from immich_memories.memory_types.registry import OFFERED_MEMORY_TYPES, MemoryType


def test_the_catalogue_is_offered_as_a_memory_type() -> None:
    assert MemoryType.SPECIAL_DAY in OFFERED_MEMORY_TYPES


def test_one_occasion_gets_one_title_card_and_no_dividers() -> None:
    """A day is not a span to divide.

    Nothing special-cases this -- a one-day range is already too short for
    dividers -- so the pin is here to catch the day somebody widens the rule.
    """
    assert get_divider_mode("special_day", date(2016, 6, 12), date(2016, 6, 13)) == "none"
