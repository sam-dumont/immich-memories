"""What `auto suggest` offers on awkward calendar days (#2361, #2362).

Each test reads the CLI's own JSON, over a fake Immich built from the real client.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from immich_memories.config_loader import Config
from tests.auto_library_fake import fake_library, suggest_json


def _config(tmp_path: Path, **automation: object) -> Config:
    return Config(
        immich={"url": "https://immich.example.test", "api_key": "key"},
        cache={"database": str(tmp_path / "runs.db"), "directory": str(tmp_path / "cache")},
        automation={"detect_trips": False, **automation},
    )


def _quiet_year_then(year: int, month: int, last: int) -> dict[str, int]:
    """Twelve quiet months before ``year-month``, then ``last`` pictures in it."""
    months = {}
    y, m = year, month
    for _ in range(12):
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        months[f"{y}-{m:02d}"] = 50
    months[f"{year}-{month:02d}"] = last
    return months


class TestALeapDayHoliday:
    @pytest.mark.feature("automation.extra-holidays-leap-day")
    def test_suggest_still_lists_candidates_in_a_year_without_29_february(
        self, tmp_path: Path
    ) -> None:
        config = _config(tmp_path, extra_holidays=["02-29: Leap day"])
        client = fake_library({"2026-05": 80, "2026-04": 60})

        rows = suggest_json(config, client, date(2026, 6, 10))

        assert ("monthly_highlights", "2026-05-01 to 2026-05-31") in {
            (row["memory_type"], row["date_range"]) for row in rows
        }

    @pytest.mark.feature("automation.extra-holidays-leap-day")
    def test_the_leap_day_is_filmed_on_28_february_in_other_years(self, tmp_path: Path) -> None:
        config = _config(tmp_path, extra_holidays=["02-29: Leap day"])
        client = fake_library({"2027-02": 80, "2027-01": 60})
        client.count_assets_with_people.return_value = 10

        rows = suggest_json(config, client, date(2027, 3, 5))

        holidays = [row for row in rows if row["memory_type"] == "holiday"]
        assert [row["date_range"] for row in holidays] == ["2023-02-26 to 2027-03-02"]
        assert holidays[0]["reason"].startswith("Leap day")

    @pytest.mark.feature("automation.extra-holidays-leap-day")
    def test_one_detector_that_breaks_costs_only_its_own_candidates(self, tmp_path: Path) -> None:
        from immich_memories.automation.season_holiday_detectors import HolidayDetector

        config = _config(tmp_path)
        client = fake_library({"2026-05": 80, "2026-04": 60})

        def broken(*_args: object, **_kwargs: object) -> list:
            raise RuntimeError("detector bug")

        # WHY: stands in for any detector bug, so the guard is proven without one existing.
        with patch.object(HolidayDetector, "due", broken):
            rows = suggest_json(config, client, date(2026, 6, 10))

        assert any(row["memory_type"] == "monthly_highlights" for row in rows)


class TestABusyMonth:
    @pytest.mark.feature("automation.busy-month-completed")
    def test_the_month_in_progress_is_not_proposed(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        client = fake_library(_quiet_year_then(2026, 10, 400))

        rows = suggest_json(config, client, date(2026, 10, 10))

        assert not [row for row in rows if row["date_range"].startswith("2026-10-01")]

    @pytest.mark.feature("automation.busy-month-completed")
    def test_once_the_month_is_over_its_full_film_is_proposed(self, tmp_path: Path) -> None:
        config = _config(tmp_path)
        client = fake_library(_quiet_year_then(2026, 10, 400))

        rows = suggest_json(config, client, date(2026, 11, 1))

        october = [row for row in rows if row["date_range"] == "2026-10-01 to 2026-10-31"]
        assert october, rows
