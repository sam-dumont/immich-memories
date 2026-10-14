"""Where a film's pictures may come from and what a trip is called, on the fixture library.

A trip's name is read off the places Immich stored on its pictures, so every run here goes
through the outbound trap and nothing may leave the machine. Which pictures a film may use at
all runs through the real Basic editor (`real_editor.py`) on a fake Immich of the test's own,
which adds forwarded copies (files a chat app saved, named the way it names them) to the
library.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from tests.e2e.fake_immich import FakeImmichServer
from tests.e2e.fake_library import BY_ID, HELD_PICTURES, HOME, Picture
from tests.features.cli_harness import OutboundTrap, UserHome, basic_config
from tests.integration.features import real_editor
from tests.integration.features.immich_server import LibraryServer
from tests.integration.features.stored_places import most_held_town, stored_places

_PICTURES = ("--include-photos", "--no-music", "--quiet")
_BIRTHDAY = "2025-07-05"


# ── a trip's name ────────────────────────────────────────────────────────────


def _trips(home: UserHome, immich: LibraryServer, away_km: int) -> list[str]:
    """The trips `generate --memory-type trip` lists when "away" starts at `away_km`."""
    config = basic_config(immich.base_url, immich.api_key, home)
    config["trips"]["min_distance_km"] = away_km
    home.write_config(config)
    listed = home.run(
        "generate", "--memory-type", "trip", "--year", "2025", *_PICTURES, scripted_selection=True
    )
    assert listed.returncode == 0, listed.explain()
    return [
        f"{m.group(1).strip()} | {m.group(2)}"
        for m in re.finditer(r"│ \d+ │ (.+?)│ (\d{4}-\d\d-\d\d to \d{4}-\d\d-\d\d)", listed.stdout)
    ]


@pytest.mark.feature("trip.named-offline")
def test_a_trip_is_named_at_the_smallest_place_holding_its_pictures_offline(
    fresh_home: UserHome, immich: LibraryServer, outbound_trap: OutboundTrap
):
    asked_before = list(outbound_trap.requests)

    # Only the two days at the cape are 2,350 km from home: nearly every picture is in one town.
    cape = _trips(fresh_home, immich, 2350)
    # From 1,950 km the trip crosses Finland and Sweden for a day, Norway the rest.
    north = _trips(fresh_home, immich, 1950)
    # From the default 50 km it is the whole drive, country after country.
    road = _trips(fresh_home, immich, 50)

    # The names are the places this Immich stored: the fake's are the fixture's own,
    # a real Immich's its GeoNames towns.
    town, country = most_held_town(immich, "2025-07-16", "2025-07-18")
    north_countries = Counter(c for _, c in stored_places(immich, "2025-07-15", "2025-07-23") if c)
    road_countries = " → ".join(
        dict.fromkeys(c for _, c in stored_places(immich, "2025-07-12", "2025-07-30") if c)
    )
    assert cape == [f"{town}, {country} | 2025-07-16 to 2025-07-18"]
    assert north == [f"{north_countries.most_common(1)[0][0]} | 2025-07-15 to 2025-07-23"]
    assert road == [f"{road_countries} | 2025-07-12 to 2025-07-30"]
    # Named from what Immich already stored on each picture: no geocoder was asked.
    assert outbound_trap.requests == asked_before


# ── forwarded copies ─────────────────────────────────────────────────────────


def _forwarded(key: str, like: Picture, name: str, *people: str, **fields) -> Picture:
    """A copy a chat app saved: a picture of the day, under the chat app's own file name."""
    return replace(
        like,
        asset_id=key,
        filename=name,
        story_key=None,
        drop_reason="a forwarded copy",
        is_favorite=False,
        people=people,
        faces=(),
        scene=key,
        **fields,
    )


_CAKE = BY_ID["birthday-cake"]
FORWARDED: tuple[Picture, ...] = (
    _forwarded("forwarded-kit", _CAKE, "IMG-20250705-WA0007.jpg", "Kit"),
    _forwarded("forwarded-pat", _CAKE, "IMG-20250705-WA0008.jpg", "Pat"),
    _forwarded("forwarded-early", BY_ID["home-0702-kit-stuffie"], "IMG-20250702-WA0003.jpg", "Kit"),
    # A registration form someone sent on the birthday: a personal document, whoever sent it.
    _forwarded(
        "forwarded-form",
        HELD_PICTURES[1],
        "IMG-20250705-WA0009.jpg",
        taken_at=_CAKE.taken_at,
        place=HOME,
        zone=HOME.zone,
    ),
)


@pytest.fixture
def forwarding_home(
    tmp_path: Path, fake_immich: FakeImmichServer, outbound_trap: OutboundTrap
) -> Iterator[UserHome]:
    server = FakeImmichServer.start(tmp_path / "immich", media_of=fake_immich, held=FORWARDED)
    try:
        yield real_editor.home_on(tmp_path / "home", server, outbound_trap.env())
    finally:
        server.close()
    assert server.refused == [], server.refused


def _why(home: UserHome, *args: str) -> dict[str, str]:
    """Cut the birthday through the real editor; what `runs why` says of each forwarded copy."""
    result = real_editor.run(
        home, "generate", "--start", _BIRTHDAY, "--end", _BIRTHDAY, *_PICTURES, *args, "--no-render"
    )
    assert result.returncode == 0, result.explain()
    found = re.search(r"runs render (\d{8}_\d{6}_[0-9a-f]{4})", result.output)
    assert found, result.explain()
    said = {}
    for picture in FORWARDED:
        why = home.run("runs", "why", picture.asset_id, "--run", found.group(1))
        assert why.returncode == 0, why.explain()
        said[picture.asset_id] = why.stdout
    return said


@pytest.mark.feature("selection.accept-any-provenance")
@pytest.mark.fake_immich_only("serves forwarded copies only a fake Immich of the test's own holds")
def test_accept_any_provenance_lets_forwarded_copies_in_within_every_other_boundary(
    forwarding_home: UserHome,
):
    camera_only = _why(forwarding_home)
    any_source = _why(forwarding_home, "--accept-any-provenance")
    kits_film = _why(forwarding_home, "--accept-any-provenance", "--person", "Kit")

    # Without the flag a forwarded copy never gets past the source check.
    for key in ("forwarded-kit", "forwarded-pat"):
        assert "left out at the source check: not shot on this camera" in camera_only[key]
    # With it, the birthday's forwarded copies reach the editor and are judged as pictures.
    for key in ("forwarded-kit", "forwarded-pat"):
        assert "not shot on this camera" not in any_source[key], any_source[key]
        assert "kept at the first cull" in any_source[key], any_source[key]
    # The date still applies: a copy from another day is not in the birthday's pool.
    assert "never reached the editor: not in this run's pool" in any_source["forwarded-early"]
    # The people still apply: Kit's film has Kit's copy and never Pat's.
    assert "kept at the first cull" in kits_film["forwarded-kit"]
    assert "never reached the editor: not in this run's pool" in kits_film["forwarded-pat"]
    # The privacy holds still apply: a forwarded document is held out like any document.
    assert (
        "held out of every film: it reads as a personal document" in (any_source["forwarded-form"])
    ), any_source["forwarded-form"]
