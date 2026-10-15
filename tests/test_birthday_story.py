"""A birthday film carries the birthday it celebrates to the editor that names its stories."""

from __future__ import annotations

from datetime import datetime

import pytest

from immich_memories.cli._editorial_context import build_editorial_context
from immich_memories.cli._run_inputs import ResolvedRunInputs
from immich_memories.config_loader import Config
from immich_memories.timeperiod import DateRange

_YEAR = DateRange(datetime(2025, 8, 31), datetime(2026, 8, 30, 23, 59, 59))
# The birthdays film's span: the oldest birthday's eve to the day after the one celebrated.
_BIRTHDAYS = DateRange(datetime(2021, 8, 29), datetime(2026, 8, 31, 23, 59, 59))


def _context(memory_type: str, preset: dict, date_range: DateRange = _YEAR):
    config = Config()
    resolved = ResolvedRunInputs.from_arguments(
        include_photos=True,
        photo_assets=None,
        dry_run=False,
        automation_attempt_id=None,
        upload_to_immich=False,
        config=config,
        person_names=["Jo"],
        music=None,
        memory_preset_params=preset,
    )
    return build_editorial_context(
        resolved=resolved,
        config=config,
        memory_type=memory_type,
        memory_key=None,
        output_stem="jo",
        assets=[],
        date_range=date_range,
        date_ranges=None,
        duration=120.0,
        transition="smart",
        title_override=None,
        person_names=["Jo"],
        accept_any_provenance=False,
    )


def test_a_birthday_film_tells_the_editor_whose_birthday_falls_when():
    assert _context("person_spotlight", {"birthday": True}).celebrated_birthday == "08-30"


def test_the_birthdays_film_names_the_birthday_not_the_day_after_it():
    preset = {"birthday": True, "birthday_years_back": 5}

    assert _context("person_spotlight", preset, _BIRTHDAYS).celebrated_birthday == "08-30"


@pytest.mark.parametrize(
    ("memory_type", "preset"),
    [("person_spotlight", {}), ("monthly_highlights", {"birthday": True})],
    ids=["person film", "not a person film"],
)
def test_no_other_film_claims_a_birthday(memory_type, preset):
    assert _context(memory_type, preset).celebrated_birthday is None


@pytest.mark.parametrize(
    ("memory_type", "preset", "occasion"),
    [
        ("person_spotlight", {"birthday": True}, "Jo's birthday"),
        ("holiday", {"holiday": "christmas", "country": "US"}, "Christmas"),
        ("trip", {"location_name": "Nordkapp"}, "Nordkapp"),
        ("monthly_highlights", {}, ""),
    ],
    ids=["birthday", "holiday", "trip", "period"],
)
def test_the_editor_knows_what_the_film_is_the_occasion_of(memory_type, preset, occasion):
    # WHY: the film's summary leads with its occasion (#2575).
    assert _context(memory_type, preset).occasion == occasion
