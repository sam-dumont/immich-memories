"""What the owner tells the editor: a hold they cleared, where home is and who is close family.

Both run through the real Basic editor. A sharing hold is a detector's answer, so that test
prepares through `scripted_preparation.py`: Basic's own preparation with the model producers
answering from the fixture library, one of them told that a picture shows someone uncovered.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from tests.e2e.fake_immich import FakeImmichServer
from tests.e2e.fake_library import household_people
from tests.features.cli_harness import CliResult, OutboundTrap, UserHome
from tests.integration.features import real_editor
from tests.integration.features.scripted_preparation import run_prepared

pytestmark = pytest.mark.fake_immich_only("scripted detector answers and plans key by fixture id")

_PICTURES = ("--include-photos", "--no-music", "--quiet")
_RUN = re.compile(r"runs render (\d{8}_\d{6}_[0-9a-f]{4})")


def _kept(home: UserHome, result: CliResult) -> str:
    assert result.returncode == 0, result.explain()
    found = _RUN.search(result.output)
    assert found, result.explain()
    return found.group(1)


@pytest.fixture
def home(tmp_path: Path, fake_immich: FakeImmichServer, outbound_trap: OutboundTrap) -> UserHome:
    return real_editor.home_on(tmp_path / "home", fake_immich, outbound_trap.env())


# ── a hold the owner cleared ─────────────────────────────────────────────────

# A day on Værøy whose cut keeps this picture; the nudity detector is told it shows someone.
_DAY = "2025-07-23"
_FLAGGED = "trip-0723-beach-stones"
_HEADS = {_FLAGGED: {"uncovered_person": "yes"}}


def _shared_cut(home: UserHome) -> str:
    """Cut the day for anyone to see; `runs why` on the flagged picture."""
    result = run_prepared(
        home,
        "generate",
        "--start",
        _DAY,
        "--end",
        _DAY,
        *_PICTURES,
        "--sharing",
        "shareable",
        "--no-render",
        heads=_HEADS,
    )
    why = home.run("runs", "why", _FLAGGED, "--run", _kept(home, result))
    assert why.returncode == 0, why.explain()
    return why.stdout


def _ok(home: UserHome, *args: str) -> str:
    result = home.run(*args)
    assert result.returncode == 0, result.explain()
    return result.output


@pytest.mark.feature("pictures.clear-hold")
def test_a_cleared_hold_lets_the_picture_into_films_up_to_its_level_until_undone(
    home: UserHome,
):
    held = _shared_cut(home)
    shown_held = _ok(home, "pictures", "show", _FLAGGED)
    family = _ok(home, "pictures", "clear-hold", _FLAGGED, "--level", "family", "--yes")
    shown_family = _ok(home, "pictures", "show", _FLAGGED)
    family_only = _shared_cut(home)
    _ok(home, "pictures", "undo", _FLAGGED)
    anyone = _ok(home, "pictures", "clear-hold", _FLAGGED, "--level", "anyone", "--yes")
    cleared = _shared_cut(home)
    listed = _ok(home, "pictures", "list")
    _ok(home, "pictures", "undo", _FLAGGED)
    undone = _shared_cut(home)
    shown_undone = _ok(home, "pictures", "show", _FLAGGED)

    assert "Held: a nudity detector flagged it." in shown_held
    assert "held it from a shareable film" in held, held
    assert f"Cleared for the family: {_FLAGGED} can play in the next cut." in family
    assert "You cleared its hold for the family (a nudity detector flagged it)." in shown_family
    # Cleared for the family is not cleared for anyone: a shared film still holds it.
    assert "held it from a shareable film" in family_only, family_only
    assert f"Cleared for anyone: {_FLAGGED}" in anyone
    assert "passed the final cut" in cleared, cleared
    assert f"{_FLAGGED}  hold cleared for anyone" in listed
    # Undone, the detector's hold applies again.
    assert "held it from a shareable film" in undone, undone
    assert "Held: a nudity detector flagged it." in shown_undone


# ── home and who's who ───────────────────────────────────────────────────────


def _stories(home: UserHome) -> list[dict]:
    result = real_editor.run(
        home, "generate", "--start", "2025-07-01", "--end", "2025-07-31", *_PICTURES, "--no-render"
    )
    plan = real_editor.plan_of(home, _kept(home, result))
    return list(plan["story"]["episodes"])


def _story_of(stories: list[dict], day: str) -> dict:
    return next(s for s in stories if s["days"][0] <= day <= s["days"][-1])


@pytest.mark.feature("who-is-who.home-and-people")
def test_home_and_whos_who_turn_ordinary_weeks_into_a_trip_and_a_family_visit(
    home: UserHome, tmp_path: Path
):
    # The same month, cut by a home that knows neither where it is nor who anyone is...
    config = yaml.safe_load(home.config_path.read_text())
    config.pop("trips")
    home.write_config(config)
    unknown = _stories(home)
    # ...and by the same home once the owner set home and who's who.
    config["trips"] = {"homebase_latitude": 50.8417, "homebase_longitude": 4.3624}
    home.write_config(config)
    document = tmp_path / "household.yaml"
    document.write_text(yaml.safe_dump(household_people(lambda name: f"person-{name.lower()}")))
    _ok(home, "people", "import", "--from", str(document))
    known = _stories(home)

    # Without a home the drive north reads as weeks at home; with one it is a trip.
    assert not [s for s in unknown if s.get("trip")], unknown
    assert _story_of(unknown, "2025-07-16").get("occasion") is None
    assert _story_of(known, "2025-07-16").get("trip") == "The road north"
    # Without who's who the grandparents' day is an ordinary one; with it, a visit of its own.
    assert _story_of(unknown, "2025-07-07").get("occasion") is None
    visit = _story_of(known, "2025-07-07")
    assert visit.get("occasion") == "visit", visit
    assert visit["days"][0] == "2025-07-07"
