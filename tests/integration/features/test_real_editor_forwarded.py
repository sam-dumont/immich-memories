"""Forwarded copies stand in only where the camera took nothing, and never size the film (#2512).

A birthdays film over three years of Kit's birthday (`--years-back 2`), through the production
Basic editor (`real_editor.py`), on a fake Immich of the test's own that adds four forwarded
copies of Kit (`fake_library.FORWARDED_COPIES`): three received around the birthday a year
before the library starts, when no camera picture was taken, and one on the birthday the camera
already holds.

- With `advanced.analysis.forwarded_copies_when_short` off (the default) no copy plays, the run
  says the earlier birthdays' pictures are copies no film uses, and the copies leave the film's
  length as it was without them.
- With it on, the copies of the year with no camera picture stand in for that year only, the
  copy on a camera day never displaces a camera picture, and each copy's shot says what it is.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from tests.e2e.fake_immich import FakeImmichServer
from tests.e2e.fake_library import FORWARDED_COPIES, household_people
from tests.features.cli_harness import OutboundTrap, UserHome
from tests.integration.features.real_editor import EditedFilm, generate, home_on

pytestmark = [
    pytest.mark.integration,
    pytest.mark.fake_immich_only("films a fake Immich of its own that adds forwarded copies"),
]

_BIRTHDAYS = (
    *("--person", "Kit", "--year", "2025", "--birthday", "07-05", "--years-back", "2"),
    *("--include-photos", "--no-music", "--quiet"),
)
_COPIES = {p.asset_id: p for p in FORWARDED_COPIES}
_NO_CAMERA_YEAR = "2024"


def _home(root: Path, server: FakeImmichServer, trap: OutboundTrap, *, stand_in: bool) -> UserHome:
    home = home_on(root / "home", server, trap.env())
    config = yaml.safe_load(home.config_path.read_text())
    config["advanced"]["analysis"] = {"forwarded_copies_when_short": stand_in}
    home.write_config(config)
    document = root / "household.yaml"
    document.write_text(yaml.safe_dump(household_people(lambda name: f"person-{name.lower()}")))
    imported = home.run("people", "import", "--from", str(document))
    assert imported.returncode == 0, imported.explain()
    return home


@pytest.fixture
def copies_immich(tmp_path: Path, fake_immich: FakeImmichServer) -> Iterator[FakeImmichServer]:
    server = FakeImmichServer.start(
        tmp_path / "immich", media_of=fake_immich, held=FORWARDED_COPIES
    )
    try:
        yield server
    finally:
        server.close()
    assert server.refused == [], server.refused


def _duration(film: EditedFilm) -> int:
    found = re.search(r"Duration (\d+)s", film.output)
    assert found, film.result.explain()
    return int(found.group(1))


def _copies_in(film: EditedFilm) -> dict[str, dict]:
    return {row["asset_id"]: row for row in film.carriers if row["asset_id"] in _COPIES}


@pytest.mark.feature("generate.length-fits-material")
def test_with_the_setting_off_no_copy_plays_or_sizes_the_film(
    tmp_path: Path, fake_immich: FakeImmichServer, copies_immich: FakeImmichServer, outbound_trap
):
    plain = generate(
        _home(tmp_path / "plain", fake_immich, outbound_trap, stand_in=False), *_BIRTHDAYS
    )
    with_copies = generate(
        _home(tmp_path / "copies", copies_immich, outbound_trap, stand_in=False), *_BIRTHDAYS
    )

    assert _copies_in(with_copies) == {}
    # The pool held them, and the run counted them out of the earlier birthdays by name.
    assert set(_COPIES) <= with_copies.pool(), sorted(with_copies.pool())
    assert "pictures there are forwarded copies or saved images, which no film uses" in (
        with_copies.output
    ), with_copies.result.explain()
    # Sized on the pictures the film may use: the copies ask for no longer a film.
    sized, unsized = _duration(with_copies), _duration(plain)
    assert sized == unsized


def test_with_the_setting_on_copies_stand_in_only_for_the_year_the_camera_missed(
    tmp_path: Path, copies_immich: FakeImmichServer, outbound_trap
):
    film = generate(_home(tmp_path, copies_immich, outbound_trap, stand_in=True), *_BIRTHDAYS)

    played = _copies_in(film)
    assert played, (film.result.explain(), [row["asset_id"] for row in film.carriers])
    assert {_COPIES[asset_id].day[:4] for asset_id in played} == {_NO_CAMERA_YEAR}
    # The camera's own birthday keeps its camera pictures.
    camera_year = [row for row in film.carriers if row["taken"].startswith("2025")]
    assert camera_year and not [row for row in camera_year if row["asset_id"] in _COPIES]
    assert all("a forwarded copy" in row["why"] for row in played.values()), played
    assert "which may stand in where the film is short" in film.output, film.result.explain()
