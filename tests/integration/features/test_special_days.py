"""The special-days catalogue from the terminal: discover-days, days-due, days-export, days-import.

The fixture library is one month, most of it a road trip, and a trip's days are the trip
film's, never special days. So each home here measures "away" from 2,350 km, where only the
two days at Nordkapp are far enough, and asks a trip to last sixty days, so those two days are
days away rather than a trip of their own. On Basic, nothing reads a picture: a day counts
from its recorded facts, here that most of its located pictures are that far from home.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest

from tests.features.cli_harness import UserHome, basic_config
from tests.integration.features.immich_server import LibraryServer
from tests.integration.features.stored_places import most_held_town

# The days the scan finds: both at Nordkapp, the furthest the trip went.
_CAPE = ("2025-07-16", "2025-07-17")


@pytest.fixture(scope="module")
def titles(immich: LibraryServer) -> dict[str, str]:
    """Each cape day's scanned title, after the town this Immich stored on its pictures."""
    return {day: f"A day in {most_held_town(immich, day, day)[0]}" for day in _CAPE}


@pytest.fixture
def home(fresh_home: UserHome, immich: LibraryServer) -> UserHome:
    config = basic_config(immich.base_url, immich.api_key, fresh_home)
    config["trips"] |= {"min_distance_km": 2350, "min_duration_days": 60}
    fresh_home.write_config(config)
    return fresh_home


def _ok(home: UserHome, *args: str) -> str:
    result = home.run(*args)
    assert result.returncode == 0, result.explain()
    return result.output


def _days(catalogue: list[dict]) -> dict[str, str]:
    """Each catalogued day's title (the catalogue's own markers left out)."""
    return {entry["day"]: entry["title"] for entry in catalogue if "day" in entry}


def _export(home: UserHome) -> list[dict]:
    result = home.run("days-export")
    assert result.returncode == 0, result.explain()
    return json.loads(result.stdout)


def _due(home: UserHome, on: str) -> list[str]:
    """The catalogued days `days-due --on` lists, as 'day title'."""
    shown = _ok(home, "days-due", "--on", on)
    return [
        f"{m.group(1)} {m.group(2)}"
        for m in re.finditer(r"ago\s+(\d{4}-\d\d-\d\d)\s+(.+?)\s{2,}", shown)
    ]


@pytest.mark.feature("special-days.discover")
def test_discover_days_catalogues_the_days_away_resumes_and_replaces_one_year(
    home: UserHome, tmp_path: Path, titles: dict[str, str]
):
    found = _ok(home, "discover-days", "--since", "2025", "--until", "2025", "--also-skip", "07-17")
    catalogue = _export(home)
    resumed = _ok(home, "discover-days", "--since", "2025", "--until", "2025")
    after_resume = _export(home)
    # The owner's own edit: a day by hand in 2025, one in 2024, and one scanned day retitled.
    edited = [
        {"day": "2024-12-24", "title": "The night before", "subtitle": "", "what": "by hand"},
        {"day": "2025-07-02", "title": "Kit learns to ride", "subtitle": "", "what": "by hand"},
        *(
            entry | {"title": "Midnight sun"} if entry.get("day") == _CAPE[0] else entry
            for entry in catalogue
        ),
    ]
    edited_file = tmp_path / "days.json"
    edited_file.write_text(json.dumps(edited))
    _ok(home, "days-import", "--from", str(edited_file))
    replaced = _ok(home, "discover-days", "--replace", "--since", "2025", "--until", "2025")
    after_replace = _days(_export(home))

    assert _days(catalogue) == titles, found
    for day in _CAPE:
        assert f"{day}  {titles[day]}" in found
    assert "2 special days in the catalogue" in found
    # --also-skip makes the date a holiday; a holiday spent away from home still counts.
    assert "2025-07-17 falls on a holiday but was spent away from home; keeping it" in found
    # A second scan resumes: the year is not read again and the catalogue stays as it was.
    assert "2025: already scanned" in resumed
    assert after_resume == catalogue
    # --replace rescans 2025 alone: its rows become the scan's, 2024 is never touched.
    assert re.search(r"--replace: re-scanning 2025-2025 and replacing the \d+ row", replaced)
    assert "1 row(s) outside the period are kept" in replaced, replaced
    assert after_replace == {"2024-12-24": "The night before"} | titles


@pytest.mark.feature("special-days.due")
def test_days_due_lists_the_anniversaries_within_three_days(home: UserHome, titles: dict[str, str]):
    _ok(home, "discover-days", "--since", "2025", "--until", "2025")

    three_before_the_first = _due(home, "2026-07-13")
    between = _due(home, "2026-07-15")
    three_after_the_last = _due(home, "2026-07-20")
    a_week_off = _due(home, "2026-07-24")
    today = _ok(home, "days-due")

    assert three_before_the_first == [f"{_CAPE[0]} {titles[_CAPE[0]]}"]
    assert between == [f"{day} {titles[day]}" for day in _CAPE]
    assert three_after_the_last == [f"{_CAPE[1]} {titles[_CAPE[1]]}"]
    assert a_week_off == []
    assert f"checked against {date.today():%Y-%m-%d}" in today or (
        f"checked against {date.fromordinal(date.today().toordinal() - 1):%Y-%m-%d}" in today
    ), today


@pytest.mark.feature("special-days.export-import")
def test_an_edited_export_replaces_the_catalogue(
    home: UserHome, tmp_path: Path, titles: dict[str, str]
):
    _ok(home, "discover-days", "--since", "2025", "--until", "2025")
    exported = tmp_path / "days.json"
    _ok(home, "days-export", "--to", str(exported))
    catalogue = json.loads(exported.read_text())
    # A missed day added, a wrong title fixed, and a day the owner doesn't want dropped.
    edited = [
        {"day": "2025-07-02", "title": "Kit learns to ride", "subtitle": "", "what": "by hand"},
        *(
            entry | {"title": "Midnight sun at the cape"} if "day" in entry else entry
            for entry in catalogue
            if entry.get("day") != _CAPE[0]
        ),
    ]
    exported.write_text(json.dumps(edited))

    imported = _ok(home, "days-import", "--from", str(exported))
    after = _export(home)

    assert _days(catalogue) == titles
    assert "catalogue records imported" in imported
    assert _days(after) == {
        "2025-07-02": "Kit learns to ride",
        _CAPE[1]: "Midnight sun at the cape",
    }
    assert _due(home, "2026-07-03") == ["2025-07-02 Kit learns to ride"]
    assert _due(home, "2026-07-16") == [f"{_CAPE[1]} Midnight sun at the cape"]
