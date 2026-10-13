"""A birthday film carries the birthday it celebrates to the editor that names its stories."""

from __future__ import annotations

from datetime import datetime

import pytest

from immich_memories.cli._editorial_context import build_editorial_context
from immich_memories.cli._run_inputs import ResolvedRunInputs
from immich_memories.config_loader import Config
from immich_memories.timeperiod import DateRange


def _context(memory_type: str, preset: dict):
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
        # Oldest flashback to the birthday celebrated, as `build_birthday_windows` spans it.
        date_range=DateRange(datetime(2021, 8, 29), datetime(2026, 8, 30, 23, 59, 59)),
        date_ranges=None,
        duration=120.0,
        transition="smart",
        title_override=None,
        person_names=["Jo"],
        accept_any_provenance=False,
    )


def test_a_birthday_film_tells_the_editor_whose_birthday_falls_when():
    assert _context("person_spotlight", {"birthday": True}).celebrated_birthday == "08-30"


@pytest.mark.parametrize(
    ("memory_type", "preset"),
    [("person_spotlight", {}), ("monthly_highlights", {"birthday": True})],
    ids=["person film", "not a person film"],
)
def test_no_other_film_claims_a_birthday(memory_type, preset):
    assert _context(memory_type, preset).celebrated_birthday is None
