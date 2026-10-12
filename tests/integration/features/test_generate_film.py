"""`generate` on the fixture library: the film, its name, its folder, and the flags that shape it."""

from __future__ import annotations

import re

import pytest

from tests.features.cli_harness import UserHome, band_luma, film_facts
from tests.integration.features.library import (
    DEPARTURE_DAY,
    RenderedRun,
    day_args,
    render,
    shipped_on,
)

# Opening card and ending card: the stretch of film that is not the pictures.
_PICTURES_START = 3.5


@pytest.mark.feature("generate.renders-a-film")
def test_generate_renders_a_playable_film_at_the_configured_resolution(departure_film: RenderedRun):
    facts = film_facts(departure_film.film)

    # The home's config asks for 720p; the day's clips are landscape.
    assert (facts.width, facts.height) == (1280, 720)
    assert facts.has_audio
    # Every shipped picture plays, between an opening and an ending card.
    shipped = sum(p.seconds if p.is_video else 0 for p in shipped_on(DEPARTURE_DAY))
    assert facts.duration > shipped
    # The film keeps its clips' frame rate: the road trip's phone was set to 25 fps.
    assert facts.fps in (25.0, 30.0)
    assert facts.frames == pytest.approx(facts.duration * facts.fps, abs=2)
    # The summary's promised length is the film's length.
    promised = re.search(r"about (\d+):(\d\d) of film", departure_film.result.stdout)
    assert promised, departure_film.result.explain()
    minutes, seconds = int(promised.group(1)), int(promised.group(2))
    assert facts.duration == pytest.approx(minutes * 60 + seconds, abs=1.0)


@pytest.mark.feature("output.output-base-name")
def test_output_names_the_film_and_the_run_adds_a_recipe_hash_and_its_own_folder(
    library_home: UserHome, departure_film: RenderedRun
):
    film = departure_film.film

    assert re.fullmatch(r"departure_[0-9a-f]{8}\.mp4", film.name), film
    assert film.parent.name == f"{film.stem}_{departure_film.run_id}"
    assert film.parent.parent == library_home.videos


@pytest.mark.feature("output.run-folder-per-render")
def test_a_rerun_writes_a_new_folder_and_keeps_the_earlier_film(
    library_home: UserHome, departure_film: RenderedRun
):
    again = render(
        library_home,
        *day_args(DEPARTURE_DAY),
        "--output",
        str(library_home.videos / "departure.mp4"),
    )

    assert again.run_id != departure_film.run_id
    assert again.film.parent != departure_film.film.parent
    # Same clips, same order, same dates: the same recipe hash names both files.
    assert again.film.name == departure_film.film.name
    assert departure_film.film.is_file()
    assert again.film.is_file()


@pytest.mark.feature("generate.photo-duration")
def test_photo_duration_sets_how_long_each_still_stays_on_screen(
    library_home: UserHome, departure_film: RenderedRun, tmp_path
):
    """The documented default holds a still 4 s; 6 s adds 2 s per still to the film."""
    longer = render(
        library_home,
        *day_args(DEPARTURE_DAY),
        "--photo-duration",
        "6",
        "--output",
        str(tmp_path / "long.mp4"),
        into=tmp_path,
    )
    stills = sum(not p.is_video for p in shipped_on(DEPARTURE_DAY))

    added = film_facts(longer.film).duration - film_facts(departure_film.film).duration

    assert stills >= 2
    assert added == pytest.approx(stills * (6.0 - 4.0), abs=0.3)


def _picture_moments(duration: float) -> list[float]:
    """Four instants inside the pictures, clear of the opening and ending cards."""
    end = duration - 3.0
    return [_PICTURES_START + (end - _PICTURES_START) * k / 4 for k in range(4)]


@pytest.mark.feature("generate.scale-mode")
@pytest.mark.feature("generate.orientation")
def test_scale_mode_fit_letterboxes_a_portrait_film_in_black(library_home: UserHome, tmp_path):
    film = render(
        library_home,
        *day_args(DEPARTURE_DAY),
        "--orientation",
        "portrait",
        "--scale-mode",
        "fit",
        "--output",
        str(tmp_path / "fit.mp4"),
        into=tmp_path,
    ).film
    facts = film_facts(film)

    assert (facts.width, facts.height) == (720, 1280)
    # Landscape pictures in a portrait frame: bars above and below, black under fit.
    assert all(band_luma(film, t) < 8 for t in _picture_moments(facts.duration))


@pytest.mark.feature("generate.scale-mode")
@pytest.mark.feature("generate.resolution")
def test_scale_mode_blur_fills_the_bars_with_the_picture_at_the_asked_resolution(
    library_home: UserHome, tmp_path
):
    film = render(
        library_home,
        *day_args(DEPARTURE_DAY),
        "--orientation",
        "portrait",
        "--scale-mode",
        "blur",
        "--resolution",
        "1080p",
        "--output",
        str(tmp_path / "blur.mp4"),
        into=tmp_path,
    ).film
    facts = film_facts(film)

    assert (facts.width, facts.height) == (1080, 1920)
    lumas = [band_luma(film, t) for t in _picture_moments(facts.duration)]
    # The blurred picture shows where fit leaves black; a dark shot may stay dim, not all of them.
    assert sum(luma > 30 for luma in lumas) >= 2, lumas
