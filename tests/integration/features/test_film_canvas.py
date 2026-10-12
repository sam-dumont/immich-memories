"""The film's canvas, transitions and captions, read from its frames."""

from __future__ import annotations

import re

import pytest

from tests.features.cli_harness import UserHome, film_facts
from tests.integration.features.cuts import cut, picture_of, story_of
from tests.integration.features.film_probe import (
    differing_columns,
    grey_frame,
)
from tests.integration.features.immich_server import LibraryServer
from tests.integration.features.library import (
    DEPARTURE_DAY,
    RenderedRun,
    day_args,
    one_day,
    render_into,
    the_day_only,
)

# A day whose one shipped picture is tall (the fixture's `portrait` still).
TALL_DAY = the_day_only(lambda p: p.portrait)


@pytest.mark.feature("generate.orientation-auto")
def test_auto_orientation_follows_the_kept_pictures(
    library_home: UserHome, departure_film: RenderedRun, tmp_path
):
    tall = render_into(library_home, tmp_path, *one_day(TALL_DAY, "--no-music"))
    square = cut(library_home, *one_day(DEPARTURE_DAY, "--no-music", "--orientation", "square"))

    # Landscape clips make a landscape film, a tall picture a tall one.
    assert (film_facts(departure_film.film).width, film_facts(departure_film.film).height) == (
        1280,
        720,
    )
    assert (film_facts(tall.film).width, film_facts(tall.film).height) == (720, 1280)
    assert re.search(r"Canvas: (\d+)x\1 \(square\)", square.output), square.output


@pytest.fixture(scope="module")
def departure_cut_and_crossfade(library_home: UserHome, tmp_path_factory):
    cuts = render_into(
        library_home,
        tmp_path_factory.mktemp("cuts"),
        *day_args(DEPARTURE_DAY),
        "--transition",
        "cut",
    )
    fades = render_into(
        library_home,
        tmp_path_factory.mktemp("fades"),
        *day_args(DEPARTURE_DAY),
        "--transition",
        "crossfade",
    )
    return cuts, fades


@pytest.mark.feature("render.transitions")
def test_crossfades_overlap_the_pictures_on_whole_frames_and_cuts_do_not(
    departure_cut_and_crossfade, departure_film: RenderedRun
):
    cuts, fades = (film_facts(r.film) for r in departure_cut_and_crossfade)
    smart = film_facts(departure_film.film)

    # Every crossfade overlaps two pictures, so the faded film is the shorter one.
    assert fades.duration < cuts.duration - 0.5
    # Smart mixes fades and cuts: it never fades more than crossfade, nor less than cut.
    assert fades.duration - 0.1 <= smart.duration <= cuts.duration + 0.1
    # Whole frames: every film's frame count is its length on its own clock (the day's clips
    # were recorded at 25 fps, and the film keeps their rate).
    for facts in (cuts, fades, smart):
        assert facts.frames == round(facts.duration * facts.fps), facts


@pytest.mark.feature("captions.date-place")
def test_captions_name_the_date_and_the_city_when_they_change_and_flags_turn_them_off(
    library_home: UserHome, immich: LibraryServer, tmp_path
):
    """Duden park in Forest, the birthday in Brussels, then the Sonian forest at Watermael-Boitsfort.

    The birthday and the forest Sunday both hold pictures without GPS: they caption no place
    and do not reset the run, so the place after them is captioned only if it changed.
    """
    days = ("--start", "2025-07-03", "--end", "2025-07-06")
    captioned = render_into(
        library_home, tmp_path / "on", "generate", *days, "--include-photos", "--no-music"
    )
    bare = render_into(
        library_home,
        tmp_path / "off",
        "generate",
        *days,
        "--include-photos",
        "--no-music",
        "--no-add-date",
        "--no-add-place",
    )
    shots = story_of(library_home, captioned.run_id)
    place_band, date_band = "iw/2:ih*0.15:0:0", "iw/2:ih*0.15:iw/2:ih*0.85"

    def reach(shot, band: str) -> float:
        at = shot.middle
        return differing_columns(
            grey_frame(captioned.film, at, band=band), grey_frame(bare.film, at, band=band)
        )

    places = [reach(s, place_band) for s in shots]
    dates = [reach(s, date_band) for s in shots]
    new_day = [i == 0 or s.day != shots[i - 1].day for i, s in enumerate(shots)]
    cities = [p.place.city if (p := picture_of(s)).place else None for s in shots]
    # A place is captioned where it differs from the last place known; no GPS shows none.
    new_city, last = [], None
    for city in cities:
        new_city.append(city is not None and city != last)
        last = city or last
    assert new_city.count(True) >= 3 and None in cities, cities
    seen = [(s.at, s.day, s.seconds, city) for s, city in zip(shots, cities, strict=True)]
    # A date where the day changes and a place where the city changes, none in between.
    assert [p > 0 for p in places] == new_city, (places, seen)
    assert [d > 0 for d in dates] == new_day, (dates, seen)
    # Every place here is in the home country, which stays out of the caption: "BRUSSELS"
    # alone reaches about a quarter of the way across the band, "BRUSSELS, BELGIUM" past
    # half of it. A real Immich names places after its own GeoNames towns: the widths are
    # the fake's names.
    if not immich.real:
        brussels = [p for p, city in zip(places, cities, strict=True) if city == "Brussels"]
        assert brussels and all(p < 0.4 for p in brussels if p > 0), places
    assert film_facts(bare.film).duration == pytest.approx(film_facts(captioned.film).duration)
