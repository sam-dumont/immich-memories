"""What a holiday film is about, for a cut being made and for one made before cuts kept it."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import TYPE_CHECKING, Any

from immich_memories.home_country import home_country
from immich_memories.memory_types.date_builders import holiday_of_window

if TYPE_CHECKING:
    from immich_memories.config_loader import Config


def holiday_params_for(memory_type: str | None, holiday: str | None, config: Config) -> dict:
    """What a holiday film is about: the holiday, the home country that dates and names it,
    and the household's own name for a day of its own (`automation.extra_holidays`)."""
    if memory_type != "holiday":
        return {}
    params = {"country": home_country(config), "holiday": holiday}
    for entry in config.automation.extra_holidays:
        month_day, _, name = entry.partition(":")
        if holiday and month_day.strip() == holiday.strip():
            params["holiday_name"] = name.strip()
    return params


def with_the_cuts_holiday(
    params: Mapping[str, Any],
    *,
    memory_type: str | None,
    start: date | None,
    end: date | None,
    config: Config,
) -> dict[str, Any]:
    """A cut's memory parameters, with the holiday a holiday cut made before cuts kept it lacks.

    Such a cut stores only its span, and a span built around a holiday says which one; without
    it a render or an upload titled the film by its dates ("December 2021 to December 2025").
    """
    kept = dict(params)
    if memory_type != "holiday" or kept.get("holiday") or start is None or end is None:
        return kept
    country = kept.get("country") or home_country(config)
    holiday = holiday_of_window(start, end, country=country)
    if holiday is None:
        return kept
    return holiday_params_for(memory_type, holiday, config) | kept | {"holiday": holiday}
