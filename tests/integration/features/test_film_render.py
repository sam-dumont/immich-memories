"""The finished film: its length, canvas, pictures, files and the run it leaves behind.

Every film here is cut from one or two fixture days so it renders in seconds. Each test asks
the film itself (ffprobe, frames) what the flag promised, beside what the run printed. Its
sound is in `test_film_sound.py`, HDR in `test_film_hdr.py`, and orientation, transitions and
captions in `test_film_canvas.py`: one file runs on one xdist worker, so the film suite is
split where its renders are.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.e2e.fake_library import ALL_PICTURES, CARRIERS, Picture
from tests.features.cli_harness import UserHome, film_facts, films_under
from tests.integration.features.cuts import cut, picture_of, story_of
from tests.integration.features.film_probe import (
    grey_frame,
    luma_difference,
    warm_side,
)
from tests.integration.features.library import (
    DEPARTURE_DAY,
    QUIET_DAY,
    RenderedRun,
    day_args,
    one_day,
    render_into,
)

# What the run attempt keeps: its status, the plan, the render it was certified for, the
# titles it was cut with, and the run it belongs to.
_PLAN_FILES = {
    "status.private.json",
    "plan.private.json",
    "render-inputs.private.json",
    "cut-titles.private.json",
    "run.private.json",
}


def _shot_of(home: UserHome, run: RenderedRun, picture: Picture):
    """The `runs story` line of one picture in a rendered run."""
    return next(s for s in story_of(home, run.run_id) if picture_of(s) == picture)


# ── a short film into an empty output directory ──────────────────────────────


@pytest.fixture(scope="module")
def short_quiet_film(library_home: UserHome, tmp_path_factory) -> tuple[RenderedRun, Path]:
    """`--short-form 30` over the quiet day, written to an output directory of its own."""
    output = tmp_path_factory.mktemp("short-form-output")
    before = films_under(output)
    result = library_home.run(
        *one_day(QUIET_DAY, "--short-form", "30", "--no-music"),
        scripted_selection=True,
        env={"IMMICH_MEMORIES_OUTPUT__DIRECTORY": str(output)},
    )
    assert result.returncode == 0, result.explain()
    films = [film for film in films_under(output) if film not in before]
    assert len(films) == 1, result.explain()
    return RenderedRun(result, films[0]), output


@pytest.mark.feature("generate.short-form")
def test_short_form_is_vertical_and_does_not_pad_a_thin_day(short_quiet_film):
    run, _ = short_quiet_film
    facts = film_facts(run.film)

    assert (facts.width, facts.height) == (720, 1280)
    # One still: far under the 30 s preset, and the film says what set the length.
    assert facts.duration < 15
    assert "Duration 30s, set by --short-form" in run.result.output


@pytest.mark.feature("generate.short-form")
def test_short_form_fills_about_thirty_seconds_from_a_full_month(library_home: UserHome):
    month = cut(
        library_home,
        "generate",
        "--start",
        "2025-07-01",
        "--end",
        "2025-07-31",
        "--include-photos",
        "--no-music",
        "--quiet",
        "--short-form",
        "30",
    )

    assert "Canvas: 720x1280 (portrait)" in month.output
    final = re.search(r"Estimated final duration: ([\d.]+)s", month.output)
    assert final and float(final.group(1)) == pytest.approx(30, abs=3), month.output


@pytest.mark.feature("output.run-leaves-behind")
def test_a_run_leaves_its_film_record_and_plan_and_nothing_else(
    library_home: UserHome, short_quiet_film
):
    run, output = short_quiet_film
    shown = library_home.run("runs", "show", run.run_id)

    # The output root holds one run folder: the film, and the run's record beside it.
    assert [p.name for p in output.iterdir()] == [run.film.parent.name]
    assert sorted(p.name for p in run.film.parent.iterdir()) == sorted(
        [run.film.name, "run_metadata.json"]
    )
    record = json.loads((run.film.parent / "run_metadata.json").read_text())
    assert (record["run_id"], record["status"]) == (run.run_id, "completed")
    assert record["output_path"] == str(run.film)
    assert run.film.parent.name.endswith(run.run_id)
    # The run record, and the plan kept beside the attempt it was cut from.
    assert shown.returncode == 0, shown.explain()
    assert "completed" in shown.stdout
    assert run.film.name in shown.stdout.replace("\n", "")
    # The cut is read back from the plan the run kept, outside the output directory.
    assert [picture_of(s) for s in story_of(library_home, run.run_id)] == [
        p for p in CARRIERS if p.taken_at.startswith(QUIET_DAY)
    ]
    # The plan files sit with the run's attempt in the cache, as the contract says.
    runs = library_home.root / ".immich-memories" / "cache" / "editorial-runs"
    [attempt] = [
        link.parent
        for link in runs.glob("*/attempts/*/run.private.json")
        if json.loads(link.read_text())["run_id"] == run.run_id
    ]
    assert {p.name for p in attempt.iterdir()} >= _PLAN_FILES
    assert json.loads((attempt / "run.private.json").read_text())["output_path"] == str(run.film)


@pytest.mark.feature("photos.edited-version")
def test_a_photo_edited_in_immich_plays_as_its_edit(library_home: UserHome, short_quiet_film):
    """The quiet day's still was mirrored in Immich's editor; its original was not.

    The tall film shows the wide picture across its middle, where the warm side of the picture
    (a yellow sign) has to sit on the side the edit put it.
    """
    run, _ = short_quiet_film
    still = next(p for p in CARRIERS if p.taken_at.startswith(QUIET_DAY))
    shot = _shot_of(library_home, run, still)

    assert still.edited
    original = warm_side(still.source)
    shown = warm_side(run.film, shot.middle, band="iw:ih*0.3:0:ih*0.35")
    assert abs(original) > 10, original
    assert shown * original < 0, (shown, original)
    assert abs(shown) > 10, shown


@pytest.mark.feature("photos.ken-burns")
def test_a_still_moves_while_it_is_on_screen(library_home: UserHome, departure_film: RenderedRun):
    """A departure-day still zooms and pans while it is on screen."""
    stills = [s for s in story_of(library_home, departure_film.run_id) if s.kind == "photo"]

    assert stills
    for shot in stills:
        early = grey_frame(departure_film.film, shot.at + 0.6, band="iw*0.6:ih*0.6:iw*0.2:ih*0.2")
        late = grey_frame(
            departure_film.film, shot.at + shot.seconds - 0.6, band="iw*0.6:ih*0.6:iw*0.2:ih*0.2"
        )
        assert luma_difference(early, late) > 2, shot


def _steps(film: Path, start: float, frames: int) -> list[float]:
    """How far the picture shifts from each frame to the next, in pixels (phase correlation)."""
    import subprocess

    import cv2
    import numpy as np

    facts = film_facts(film)
    raw = subprocess.run(  # noqa: S603, S607 - our own film, fixed argv
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            f"{start:.3f}",
            "-i",
            str(film),
            "-frames:v",
            str(frames),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    stack = np.frombuffer(raw, np.uint8).reshape(-1, facts.height, facts.width).astype(np.float32)
    window = cv2.createHanningWindow((facts.width, facts.height), cv2.CV_32F)
    return [
        float(np.hypot(*cv2.phaseCorrelate(a, b, window)[0]))
        for a, b in zip(stack, stack[1:], strict=False)
    ]


@pytest.mark.feature("photos.ken-burns")
def test_a_still_moves_in_even_steps_at_the_films_own_rate(
    library_home: UserHome, departure_film: RenderedRun
):
    """#2475: a still animated at 30 fps in a 25 fps film lost a frame in six, and every fifth
    step was twice as long as the ones around it."""
    facts = film_facts(departure_film.film)
    assert round(facts.fps) == 25, "the departure day's clips make a 25 fps film"
    stills = [s for s in story_of(library_home, departure_film.run_id) if s.kind == "photo"]

    assert stills
    for shot in stills:
        steps = _steps(departure_film.film, shot.started, int(facts.fps))
        typical = sorted(steps)[len(steps) // 2]
        assert max(steps) < 1.5 * typical + 0.1, (shot, [round(v, 2) for v in steps])


# ── length ───────────────────────────────────────────────────────────────────


@pytest.mark.feature("generate.duration")
def test_duration_budgets_the_whole_film_titles_included(library_home: UserHome, tmp_path):
    budgeted = render_into(library_home, tmp_path, *day_args(DEPARTURE_DAY), "--duration", "14")

    assert film_facts(budgeted.film).duration <= 14 + 0.5
    assert "set by --duration" in budgeted.result.output


@pytest.mark.feature("generate.length-fits-material")
def test_without_duration_the_material_sets_the_length_and_the_run_says_so(
    library_home: UserHome, departure_film: RenderedRun
):
    month = cut(
        library_home,
        "generate",
        "--start",
        "2025-07-01",
        "--end",
        "2025-07-31",
        "--include-photos",
        "--no-music",
        "--quiet",
    )

    day = re.search(
        r"Duration (\d+)s, set by the material: 1 photographed days", departure_film.result.output
    )
    whole = re.search(
        r"Duration (\d+)s, set by the material: (\d+) photographed days", month.output
    )
    assert day and whole, (departure_film.result.output[-2000:], month.output[-2000:])
    # A month of days asks for more film than one afternoon does.
    assert int(whole.group(1)) > int(day.group(1))
    assert int(whole.group(2)) == len({p.day for p in ALL_PICTURES})
    # And the finished film is no longer than the length the material set.
    assert film_facts(departure_film.film).duration <= int(day.group(1)) + 0.5


# ── names ────────────────────────────────────────────────────────────────────


@pytest.mark.feature("output.default-names")
def test_a_trip_film_is_named_after_its_place_and_first_day(library_home: UserHome, tmp_path):
    run = library_home.run(
        "generate",
        "--memory-type",
        "trip",
        "--year",
        "2025",
        "--trip-index",
        "1",
        "--include-photos",
        "--no-music",
        "--quiet",
        scripted_selection=True,
        env={"IMMICH_MEMORIES_OUTPUT__DIRECTORY": str(tmp_path)},
    )

    assert run.returncode == 0, run.explain()
    [film] = films_under(tmp_path)
    assert re.fullmatch(
        r"trip_denmark_sweden_finland_norway_2025-07-12_[0-9a-f]{8}\.mp4", film.name
    ), film
    assert re.fullmatch(rf"{film.stem}_\d{{8}}_\d{{6}}_[0-9a-f]{{4}}", film.parent.name)


@pytest.mark.feature("output.default-names")
def test_an_album_film_is_named_after_the_album(library_home: UserHome):
    planned = library_home.run(
        "generate",
        "--from-album",
        "The road north",
        "--include-photos",
        "--no-music",
        "--dry-run",
        scripted_selection=True,
    )

    assert planned.returncode == 0, planned.explain()
    assert re.search(
        r"album_the_road_north_<recipe>_<run id>/album_the_road_north_<recipe>\.mp4", planned.stdout
    ), planned.stdout


def _still_clip(
    tmp_path: Path,
    name: str,
    faces: list[tuple[int, int, int]],
    *,
    subjects: tuple[int, ...] = (),
) -> tuple[bytes, bytes]:
    """Render a marked still with these recognised faces; its first and last frames, in grey.

    `faces` are (left, top, size) boxes Immich recognised, on a 1920x1080 thumbnail,
    each a different named person and drawn white on the still; the four corners
    are black. `subjects` are the indices of the people the film is about.
    """
    from PIL import Image, ImageDraw

    from immich_memories.api.models import AssetFace, AssetType, Person
    from immich_memories.config_models_render import PhotoConfig
    from immich_memories.photos.photo_pipeline import render_single_photo
    from tests.conftest import make_asset

    marked = Image.new("L", (1920, 1080), 90)
    draw = ImageDraw.Draw(marked)
    for x, y in ((0, 0), (1800, 0), (0, 960), (1800, 960)):
        draw.rectangle((x, y, x + 119, y + 119), fill=0)
    for x, y, size in faces:
        draw.rectangle((x, y, x + size, y + size), fill=255)
    source = tmp_path / f"{name}.png"
    marked.convert("RGB").save(source)
    people = [
        Person(
            id=f"person-{n}",
            name=f"Person {n}",
            faces=[
                AssetFace(
                    id=f"face-{n}",
                    boundingBoxX1=x,
                    boundingBoxY1=y,
                    boundingBoxX2=x + size,
                    boundingBoxY2=y + size,
                    imageWidth=1920,
                    imageHeight=1080,
                )
            ],
        )
        for n, (x, y, size) in enumerate(faces)
    ]
    # One asset id for every render: the move is seeded from it.
    asset = make_asset("ken-burns-still").model_copy(
        update={"type": AssetType.IMAGE, "people": people}
    )
    (tmp_path / name).mkdir()
    clip = render_single_photo(
        asset,
        PhotoConfig(duration=2),
        640,
        360,
        tmp_path / name,
        None,
        fps=10,
        source_path=source,
        subjects=tuple(f"Person {n}" for n in subjects),
    )
    assert clip is not None
    return grey_frame(clip.path, 0.0), grey_frame(clip.path, 1.9)


def _corners_shown(frame: bytes) -> int:
    """How many of the still's four black corners a 160x90 grey frame shows."""
    corners = ((2, 2), (157, 2), (2, 87), (157, 87))
    return sum(1 for x, y in corners if frame[y * 160 + x] < 40)


def _corner_sides(frame: bytes) -> set[str]:
    """Which sides' black corners a 160x90 grey frame shows: both corners of a side, or none."""
    sides = {"left": ((2, 2), (2, 87)), "right": ((157, 2), (157, 87))}
    return {
        side for side, corners in sides.items() if all(frame[y * 160 + x] < 40 for x, y in corners)
    }


def _white(frame: bytes) -> list[int]:
    return [n for n, value in enumerate(frame) if value > 200]


@pytest.mark.feature("photos.ken-burns")
def test_a_still_moves_between_the_whole_picture_and_what_the_film_is_about(tmp_path):
    # A person film: the whole picture first, then a push-in on the small face on
    # the left, away from the bigger one on the right.
    first, last = _still_clip(tmp_path, "person", [(200, 500, 80), (1500, 300, 260)], subjects=(0,))
    assert _corners_shown(first) == 4
    assert _corners_shown(last) < 4
    left_white = [n for n in _white(last) if n % 160 < 80]
    assert len(left_white) > 1.4 * len([n for n in _white(first) if n % 160 < 80])

    # A group film: the closest frame keeps every face and is a real zoom.
    group = [(500, 400, 90), (800, 380, 100), (1100, 420, 90)]
    first, last = _still_clip(tmp_path, "group", group, subjects=(0, 1, 2))
    assert _corners_shown(first) == 4
    assert _corners_shown(last) == 0
    columns = sorted({n % 160 for n in _white(last)})
    # Three white faces still on screen: three runs of columns.
    runs = 1 + sum(1 for a, b in zip(columns, columns[1:], strict=False) if b > a + 1)
    assert runs == 3, columns

    # A picture with nobody in it drifts: this one pans across its long side at a gentle
    # zoom, so each end shows the two corners of its own side, and the sides are opposite.
    first, last = _still_clip(tmp_path, "no-face", [])
    assert (
        _corner_sides(first) == {"left"}
        and _corner_sides(last) == {"right"}
        or (_corner_sides(first) == {"right"} and _corner_sides(last) == {"left"})
    ), (_corner_sides(first), _corner_sides(last))
