"""A holiday film over several years: each year's day is its own story and leads it (#2512).

Through the production Basic editor (`real_editor.py`), on a fake Immich of the test's own that
adds two starred camera pictures of each of the two fourths of July before the library starts
(`fake_library.EARLIER_HOLIDAYS`). The film of `--holiday 07-04` over three years:

- is titled with the holiday's name and the span of years its cut shows, first to last;
- tells each year's day as a story of its own, never folding two years into one;
- shows every year, and in each the holiday itself leads: its first shot is on the day, and the
  days around it only fill in.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.e2e.fake_immich import FakeImmichServer
from tests.e2e.fake_library import EARLIER_HOLIDAYS
from tests.features.cli_harness import OutboundTrap
from tests.integration.features.real_editor import generate, home_on

pytestmark = [
    pytest.mark.integration,
    pytest.mark.fake_immich_only("films a fake Immich of its own that adds earlier years"),
]

_HOLIDAY = "07-04"
_YEARS = ("2023", "2024", "2025")


@pytest.fixture
def years_immich(tmp_path: Path, fake_immich: FakeImmichServer) -> Iterator[FakeImmichServer]:
    server = FakeImmichServer.start(
        tmp_path / "immich", media_of=fake_immich, held=EARLIER_HOLIDAYS
    )
    try:
        yield server
    finally:
        server.close()
    assert server.refused == [], server.refused


@pytest.mark.feature("memory-type.holiday")
def test_a_holiday_over_three_years_tells_each_years_day_and_lets_it_lead(
    tmp_path: Path, years_immich: FakeImmichServer, outbound_trap: OutboundTrap
):
    home = home_on(tmp_path / "home", years_immich, outbound_trap.env())

    film = generate(
        home,
        *("--memory-type", "holiday", "--holiday", _HOLIDAY, "--year", "2025"),
        *("--years-back", "3", "--include-photos", "--no-music", "--quiet"),
    )

    titles = json.loads(
        (Path(film.plan["__attempt_dir__"]) / "cut-titles.private.json").read_text()
    )
    days = [row["taken"][:10] for row in film.carriers]
    years = sorted({day[:4] for day in days})
    assert years == list(_YEARS), days
    assert titles["title"] == f"4 July · {years[0]}–{years[-1]}", titles
    for story in film.plan["story"]["episodes"]:
        assert len({day[:4] for day in story["days"]}) == 1, story
    for year in _YEARS:
        shots = [day for day in days if day.startswith(year)]
        on_the_day = Counter(day.endswith(_HOLIDAY) for day in shots)
        assert shots[0].endswith(_HOLIDAY), (year, shots)
        assert on_the_day[True] > on_the_day[False], (year, shots)
