"""Whole films chosen by the real Basic editor on the fixture library, checked against its rules.

A year, a trip and a person film go through `generate` with production selection (no model, no
scripted editor; see `real_editor.py`), are rendered, and are read back from what the run
recorded: the cut its attempt kept, `runs story`, `runs why` and the film file. Each one is held
to the editing rules the docs promise (how-it-chooses/ and reference/selection-internals/):

- a favourite wins its moment, and the near-identical frames beside it never join it;
- the film plays in capture order;
- a starred screenshot and a starred photographed form stay out all the same;
- a person film shows only pictures that person is recognised on;
- the film keeps to the length it was asked for.

Every expectation is derived from the fixture library's own pictures (`fake_library.py`).
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pytest

from tests.e2e.fake_immich import FakeImmichServer
from tests.e2e.fake_library import CAST, HELD_PICTURES, HOME, LIBRARY, Picture
from tests.features.cli_harness import OutboundTrap, film_facts
from tests.integration.features.real_editor import (
    SERVED,
    EditedFilm,
    generate,
    home_on,
    library_with_held,
    run,
)

# The held pictures (a starred screenshot and form) sit only on a fake Immich of the test's own:
# seeding them into the shared real library would put them in every other test's pool.
pytestmark = pytest.mark.fake_immich_only(
    "films a fake Immich of its own that adds the held pictures to the library"
)

YEAR = LIBRARY[0].taken_at[:4]
_RENDER = ("--include-photos", "--no-music", "--quiet")
# What ffprobe reads past the planned length: the last frame's own duration and AAC priming.
_CONTAINER_SLACK = 0.5


@pytest.fixture
def held_immich(tmp_path: Path, fake_immich: FakeImmichServer):
    """This test's own fake Immich: the library, plus the starred pictures that must stay out."""
    with library_with_held(tmp_path / "immich", fake_immich) as server:
        yield server


@pytest.fixture
def home(tmp_path: Path, held_immich: FakeImmichServer, outbound_trap: OutboundTrap):
    return home_on(tmp_path / "home", held_immich, outbound_trap.env())


# ── the rules, read on a finished cut ────────────────────────────────────────

# Two stills of one scene this close in time are one picture taken twice.
_NEAR_IDENTICAL_SECONDS = 120


def _scene(picture: Picture) -> list[Picture]:
    """A picture and the near-identical frames the library holds beside it (minutes apart)."""
    return [p for p in SERVED.values() if p.scene == picture.scene]


def assert_capture_order(film: EditedFilm) -> None:
    kept = film.kept()
    assert [p.taken_at for p in kept] == sorted(p.taken_at for p in kept), [
        p.asset_id for p in kept
    ]
    assert [s.at for s in film.shots] == sorted(s.at for s in film.shots)
    assert [s.day for s in film.shots] == [p.day for p in kept]


def assert_favourites_win_their_moment(film: EditedFilm) -> None:
    """Where a moment holds a star, the star plays for it, by the editor's moments and the library's.

    A video beside it is a shot of its own (a video is never a repeat of a still), so it may
    play too; a still never takes the star's place.
    """
    pool = film.pool()
    kept = {p.asset_id for p in film.kept()}
    for picture in film.kept():
        starred = {
            p.asset_id
            for p in SERVED.values()
            if p.is_favorite
            and p.asset_id in pool
            and (p.asset_id in film.moment_of(picture) or p.scene == picture.scene)
        }
        if not starred or picture.asset_id in starred:
            continue
        assert picture.is_video and starred & kept, (
            f"{picture.asset_id} plays for a moment whose favourite {sorted(starred)} does not"
        )


def _seconds_apart(left: Picture, right: Picture) -> float:
    def instant(picture: Picture) -> datetime:
        return datetime.fromisoformat(picture.taken_at.replace("Z", "+00:00"))

    return abs((instant(left) - instant(right)).total_seconds())


def assert_one_frame_per_moment(film: EditedFilm) -> None:
    """Near-identical stills (the same scene, minutes apart) compete for one place.

    A scene is one photographer's run of shots without a long gap, so two of its stills half
    an hour apart are two pictures; two taken within a couple of minutes are the same one.
    """
    stills = [p for p in film.kept() if not p.is_video]
    for index, picture in enumerate(stills):
        twins = [
            p
            for p in stills[index + 1 :]
            if p.scene == picture.scene and _seconds_apart(p, picture) <= _NEAR_IDENTICAL_SECONDS
        ]
        assert not twins, [picture.asset_id, *(p.asset_id for p in twins)]


def assert_held_out(home, film: EditedFilm) -> list[Picture]:
    """Each held picture the period holds reached the editor, starred, and stayed out.

    `runs why` names the hold: the screen size of a screenshot, the document Immich's OCR read.
    """
    held = [p for p in HELD_PICTURES if p.asset_id in film.pool()]
    kept = {p.asset_id for p in film.kept()}
    for picture in held:
        assert picture.is_favorite
        assert picture.asset_id not in kept, f"{picture.asset_id} plays in the film"
        why = run(home, "runs", "why", picture.asset_id, "--run", film.run_id)
        assert why.returncode == 0, why.explain()
        named = "document" if picture.ocr else "screenshot"
        assert named in why.stdout and "passed the final cut" not in why.stdout, why.stdout
    return held


def assert_vouched_before_a_favourite_leaves(film: EditedFilm) -> None:
    """A favourite is never dropped while a shot nothing vouches for still plays."""
    kept = film.kept()
    held = {p.asset_id for p in HELD_PICTURES}
    left_out = [
        p
        for p in SERVED.values()
        if p.is_favorite
        and p.asset_id in film.pool()
        and p.asset_id not in held
        and p not in kept
        and not any(k.scene == p.scene for k in kept)
    ]
    if left_out:
        unvouched = [p.asset_id for p in kept if not (p.is_favorite or p.is_video or p.people)]
        assert not unvouched, (
            f"{[p.asset_id for p in left_out]} left out while {unvouched} play, vouched for by nothing"
        )


def assert_within(film: EditedFilm, seconds: float) -> None:
    assert film_facts(film.film).duration <= seconds + _CONTAINER_SLACK, film.output


def assert_the_editing_rules(home, film: EditedFilm) -> None:
    assert film.kept(), film.output
    assert_capture_order(film)
    assert_favourites_win_their_moment(film)
    assert_one_frame_per_moment(film)
    assert_vouched_before_a_favourite_leaves(film)
    assert_held_out(home, film)


# ── the films ────────────────────────────────────────────────────────────────


@pytest.mark.feature(
    "selection.real-editor-rules",
    "privacy.documents-held",
    "memory-type.year-in-review",
    "generate.duration",
)
def test_a_year_through_the_real_editor_keeps_its_rules_and_its_minute(home):
    seconds = 60
    year = generate(
        home,
        "--memory-type",
        "year_in_review",
        "--year",
        YEAR,
        "--duration",
        str(seconds),
        *_RENDER,
    )

    assert_the_editing_rules(home, year)
    # Both held pictures fall in the year, so both reached the editor and both stayed out.
    assert {p.asset_id for p in assert_held_out(home, year)} == {p.asset_id for p in HELD_PICTURES}
    assert f"Duration {seconds}s, set by --duration" in year.output, year.result.explain()
    assert_within(year, seconds)


def _away(picture: Picture) -> bool:
    """Taken more than a day's drive from home: over a degree of latitude or longitude away.

    Only a picture whose file holds GPS can say where it was taken.
    """
    place = picture.place
    return place is not None and (
        abs(place.latitude - HOME.latitude) > 1 or abs(place.longitude - HOME.longitude) > 1
    )


@pytest.mark.feature("selection.real-editor-rules", "privacy.documents-held", "memory-type.trip")
def test_a_trip_through_the_real_editor_films_the_time_away_by_its_rules(home):
    away = [p for p in LIBRARY if _away(p)]
    trip = generate(
        home,
        "--memory-type",
        "trip",
        "--year",
        YEAR,
        "--near-date",
        min(p.day for p in away),
        *_RENDER,
    )

    window = re.search(r"Generating trip: .+ \((\d{4}-\d\d-\d\d) to (\d{4}-\d\d-\d\d)", trip.output)
    assert window, trip.result.explain()
    first, last = window.groups()
    # The trip is the stretch of days the library spent away.
    assert (first, last) == (min(p.day for p in away), max(p.day for p in away))
    kept = trip.kept()
    # Its photos were taken away; its clips (a phone writes no GPS into them) are the trip's days.
    assert all(first <= p.day <= last and (p.is_video or _away(p)) for p in kept), [
        p.asset_id for p in kept
    ]
    assert_the_editing_rules(home, trip)
    # The form photographed at the campsite is in the trip's pool, starred, and stays out.
    assert [p.asset_id for p in assert_held_out(home, trip)] == [
        p.asset_id for p in HELD_PICTURES if first <= p.day <= last and _away(p)
    ]
    target = re.search(r"Duration (\d+)s", trip.output)
    assert target, trip.result.explain()
    assert_within(trip, float(target.group(1)))


@pytest.mark.feature("selection.real-editor-rules", "memory-type.person-spotlight")
def test_a_person_film_through_the_real_editor_shows_them_on_every_picture(home):
    person = max(CAST, key=lambda name: sum(name in p.people for p in LIBRARY))
    spotlight = generate(
        home, "--memory-type", "person_spotlight", "--person", person, "--year", YEAR, *_RENDER
    )

    assert spotlight.pool() == {p.asset_id for p in SERVED.values() if person in p.people}
    kept = spotlight.kept()
    # Strict per picture: recognised on that very picture, not merely on the same afternoon.
    assert all(person in p.people for p in kept), [
        (p.asset_id, p.people) for p in kept if person not in p.people
    ]
    assert_the_editing_rules(home, spotlight)
    target = re.search(r"Duration (\d+)s", spotlight.output)
    assert target, spotlight.result.explain()
    assert_within(spotlight, float(target.group(1)))
