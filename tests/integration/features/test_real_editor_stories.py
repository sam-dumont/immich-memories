"""The real editor names a month's stories the way the household would (#2486).

Through the production Basic editor (no model, `real_editor.py`), on a home whose registry
knows the household (`fake_library.household_people`): the birthday and the grandparents' visit
are stories of their own, named from their facts, and the road north is one trip in legs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.e2e.fake_immich import FakeImmichServer
from tests.e2e.fake_library import household_people
from tests.features.cli_harness import OutboundTrap, UserHome
from tests.integration.features.real_editor import generate, home_on

pytestmark = [pytest.mark.integration, pytest.mark.fake_immich_only("reads the plan's stories")]

_MONTH = (
    "--start",
    "2025-07-01",
    "--end",
    "2025-07-31",
    "--include-photos",
    "--no-music",
    "--quiet",
)
_WEIGHTS = ("dominant", "major", "minor", "glimpse", "none")


@pytest.fixture
def home(tmp_path: Path, fake_immich: FakeImmichServer, outbound_trap: OutboundTrap) -> UserHome:
    home = home_on(tmp_path / "home", fake_immich, outbound_trap.env())
    document = tmp_path / "household.yaml"
    document.write_text(yaml.safe_dump(household_people(lambda name: f"person-{name.lower()}")))
    imported = home.run("people", "import", "--from", str(document))
    assert imported.returncode == 0, imported.explain()
    return home


@pytest.mark.feature("selection.story-names")
def test_a_month_through_the_real_editor_names_its_occasions_and_its_trip(home: UserHome):
    month = generate(home, *_MONTH)
    stories = {s["title"]: s for s in month.plan["story"]["episodes"]}

    assert not [title for title in stories if " / " in title], list(stories)
    birthday = stories["Kit's birthday"]
    assert (birthday["occasion"], birthday["purpose"], birthday["days"]) == (
        "birthday",
        "Kit turns five",
        ["2025-07-05", "2025-07-05"],
    )
    visit = stories["Pat and Lou's visit"]
    assert (visit["occasion"], visit["days"][0]) == ("visit", "2025-07-07")
    legs = [s for s in stories.values() if s.get("trip")]
    assert legs, list(stories)
    assert {s["trip"] for s in legs} == {"The road north"}, [
        (s["trip"], s["title"], s["days"], s["places"]) for s in legs
    ]
    ordinary = [s for s in stories.values() if s.get("occasion") is None]
    for occasion in (birthday, visit):
        assert all(
            _WEIGHTS.index(occasion["weight"]) <= _WEIGHTS.index(o["weight"]) for o in ordinary
        ), (occasion["title"], occasion["weight"], [(o["title"], o["weight"]) for o in ordinary])
