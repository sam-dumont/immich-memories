"""`auto suggest` shows an on-this-day proposal's source years, not a one-day window (#2199)."""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock

from immich_memories.automation.calendar_detectors import OnThisDayDetector
from immich_memories.cli._helpers import console
from immich_memories.cli.auto_cmd import _candidates_to_json, _print_candidates_table


def _on_this_day():
    assets = {f"{year}-10": 10 for year in range(2017, 2022)}
    return OnThisDayDetector().detect(assets, [], set(), MagicMock(), date(2026, 10, 6))


def test_the_table_names_the_years_an_on_this_day_film_draws_from():
    with console.capture() as captured:
        _print_candidates_table(_on_this_day())

    text = " ".join(captured.get().split())
    assert "2017" in text
    assert "2021" in text
    assert "2026-10-06 to 2026-10-06" not in text


def test_the_json_lists_the_source_years():
    rows = json.loads(_candidates_to_json(_on_this_day()))

    assert rows[0]["source_years"] == [2017, 2018, 2019, 2020, 2021]
