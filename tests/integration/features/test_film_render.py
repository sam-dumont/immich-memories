"""The finished film: its length, canvas, pictures, sound, transitions, captions and files.

Every film here is cut from one or two fixture days so it renders in seconds. Each test asks
the film itself (ffprobe, frames, loudness) what the flag promised, beside what the run printed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.e2e.fake_library import ALL_PICTURES, CARRIERS, Picture
from tests.features.cli_harness import UserHome, basic_config, film_facts, films_under
from tests.integration.features.cuts import cut, picture_of, story_of
from tests.integration.features.film_probe import (
    differing_columns,
    grey_frame,
    loudness,
    luma_difference,
    luma_levels,
    video_stream,
    warm_side,
)
from tests.integration.features.immich_server import LibraryServer
from tests.integration.features.library import (
    GARDEN_DAY,
    QUIET_DAY,
    RenderedRun,
    day_args,
    render,
)

# A day of one clip with its own sound recorded (the fixture's `voiced` clip) and no stills.
HUM_DAY = "2024-06-04"
HUM_HZ = 220
# A day whose one shipped picture is tall (the fixture's `portrait` still).
TALL_DAY = "2024-06-29"
TRACK_HZ = 660
# A day of one still saved with an HDR gain map (the fixture's `hdr` photo).
HDR_DAY = "2024-06-01"
# The PQ code of diffuse white (203 nits) in a 10-bit film: HDR highlights sit above it.
_PQ_DIFFUSE_WHITE = 572
_TITLE = 3.0
# What the run attempt keeps: its status, the plan, the render it was certified for, the
# titles it was cut with, and the run it belongs to.
_PLAN_FILES = {
    "status.private.json",
    "plan.private.json",
    "render-inputs.private.json",
    "cut-titles.private.json",
    "run.private.json",
}


def _day(day: str, *extra: str) -> tuple[str, ...]:
    return ("generate", "--start", day, "--end", day, "--include-photos", "--quiet", *extra)


def _render_into(home: UserHome, directory: Path, *args: str) -> RenderedRun:
    return render(home, *args, "--output", str(directory / "film.mp4"), into=directory)


@pytest.fixture(scope="module")
def own_track(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A music file of your own: a steady 660 Hz note, long enough for any film here."""
    import subprocess

    track = tmp_path_factory.mktemp("music") / "track.wav"
    subprocess.run(  # noqa: S603 -- fixed ffmpeg argv
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={TRACK_HZ}:duration=60",
            "-ac",
            "2",
            "-y",
            str(track),
        ],
        check=True,
    )
    return track


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
        *_day(QUIET_DAY, "--short-form", "30", "--no-music"),
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
        "2024-06-01",
        "--end",
        "2024-06-30",
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
    """The quiet day's still was turned upside down in Immich's editor; its original was not.

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
def test_a_still_moves_while_it_is_on_screen(library_home: UserHome, garden_film: RenderedRun):
    """No face recognised on the garden stills: the gentle zoom and pan head for the centre."""
    stills = [s for s in story_of(library_home, garden_film.run_id) if s.kind == "photo"]

    assert stills
    for shot in stills:
        early = grey_frame(garden_film.film, shot.at + 0.6, band="iw*0.6:ih*0.6:iw*0.2:ih*0.2")
        late = grey_frame(
            garden_film.film, shot.at + shot.seconds - 0.6, band="iw*0.6:ih*0.6:iw*0.2:ih*0.2"
        )
        assert luma_difference(early, late) > 2, shot


@pytest.mark.feature("hdr.end-to-end")
def test_a_gain_mapped_photo_keeps_hdr_in_an_hdr_h265_film_and_is_tone_mapped_in_sdr(
    library_home: UserHome, immich: LibraryServer, tmp_path
):
    still = next(p for p in CARRIERS if p.taken_at.startswith(HDR_DAY))
    home = UserHome(tmp_path / "hdr-home")
    config = basic_config(immich.base_url, immich.api_key, home)
    config["output"].update(codec="h265", hdr_mode="auto")
    home.write_config(config)

    hdr = render(home, *_day(HDR_DAY, "--no-music"))
    plain = render(home, *_day(QUIET_DAY, "--no-music"))
    sdr = _render_into(library_home, tmp_path / "sdr", *_day(HDR_DAY, "--no-music"))

    assert still.hdr
    stream = video_stream(hdr.film)
    assert (stream["codec_name"], stream["pix_fmt"], stream["color_transfer"]) == (
        "hevc",
        "yuv420p10le",
        "smpte2084",
    )
    middle = story_of(home, hdr.run_id)[0]
    _, peak = luma_levels(hdr.film, middle.middle)
    assert peak > _PQ_DIFFUSE_WHITE + 40, peak
    # The same settings with a plain photo stay SDR: the gain map is what made the film HDR.
    assert video_stream(plain.film)["color_transfer"] == "bt709"
    # An SDR film tone-maps it: BT.709, 8 bits, and no dimmer than the picture itself.
    sdr_stream = video_stream(sdr.film)
    assert (sdr_stream["codec_name"], sdr_stream["color_transfer"]) == ("h264", "bt709")
    shot = story_of(library_home, sdr.run_id)[0]
    mean, peak = luma_levels(sdr.film, shot.middle)
    picture_mean, _ = luma_levels(still.source, 0, convert="format=yuv420p")
    assert mean > 0.9 * picture_mean, (mean, picture_mean)
    assert peak <= 235


# ── length ───────────────────────────────────────────────────────────────────


@pytest.mark.feature("generate.duration")
def test_duration_budgets_the_whole_film_titles_included(library_home: UserHome, tmp_path):
    budgeted = _render_into(library_home, tmp_path, *day_args(GARDEN_DAY), "--duration", "14")

    assert film_facts(budgeted.film).duration <= 14 + 0.5
    assert "set by --duration" in budgeted.result.output


@pytest.fixture
def bundled_tracks() -> None:
    """The bundled tracks the `music` extra installs; `make dev-test-features` adds it.

    Without them a run rightly adds no music and says so, and the tests below would read that
    as a broken fallback rather than a missing install.
    """
    from immich_memories.audio.bundled_music import bundled_library

    assert bundled_library() is not None, "the music extra is missing: make dev-test-features"


@pytest.mark.feature("generate.duration")
@pytest.mark.feature("music.bundled-default")
@pytest.mark.usefixtures("bundled_tracks")
def test_a_thin_day_finishes_short_of_its_duration_with_a_bundled_track(
    library_home: UserHome, tmp_path
):
    """No --music and no generator configured: automatic music is a bundled track."""
    run = _render_into(library_home, tmp_path, *_day(QUIET_DAY, "--duration", "60"))
    facts = film_facts(run.film)

    assert facts.duration < 30
    mean, _ = loudness(run.film)
    assert mean > -40, mean
    assert "Optional music failed" not in run.result.output


@pytest.mark.feature("generate.length-fits-material")
def test_without_duration_the_material_sets_the_length_and_the_run_says_so(
    library_home: UserHome, garden_film: RenderedRun
):
    month = cut(
        library_home,
        "generate",
        "--start",
        "2024-06-01",
        "--end",
        "2024-06-30",
        "--include-photos",
        "--no-music",
        "--quiet",
    )

    day = re.search(
        r"Duration (\d+)s, set by the material: 1 photographed days", garden_film.result.output
    )
    whole = re.search(
        r"Duration (\d+)s, set by the material: (\d+) photographed days", month.output
    )
    assert day and whole, (garden_film.result.output[-2000:], month.output[-2000:])
    # A month of days asks for more film than one afternoon does.
    assert int(whole.group(1)) > int(day.group(1))
    assert int(whole.group(2)) == len({p.taken_at[:10] for p in ALL_PICTURES})
    # And the finished film is no longer than the length the material set.
    assert film_facts(garden_film.film).duration <= int(day.group(1)) + 0.5


# ── music and the clips' own sound ───────────────────────────────────────────


@pytest.fixture(scope="module")
def hum_with_track(library_home: UserHome, own_track: Path, tmp_path_factory) -> RenderedRun:
    directory = tmp_path_factory.mktemp("hum-loud")
    return _render_into(
        library_home, directory, *_day(HUM_DAY, "--music", str(own_track), "--music-volume", "0.8")
    )


def _clip_window(home: UserHome, run: RenderedRun) -> tuple[float, float]:
    shot = story_of(home, run.run_id)[0]
    return shot.at + 0.5, shot.at + shot.seconds - 0.5


@pytest.mark.feature("music.own-track")
def test_your_own_track_plays_and_drops_under_the_clips_own_sound(
    library_home: UserHome, hum_with_track: RenderedRun
):
    film = hum_with_track.film
    start, end = _clip_window(library_home, hum_with_track)

    over_title, _ = loudness(film, 0.5, _TITLE - 0.5, tone=TRACK_HZ)
    over_clip, _ = loudness(film, start, end, tone=TRACK_HZ)
    hum, _ = loudness(film, start, end, tone=HUM_HZ)

    assert over_title > -45, over_title
    # The clip's own recording stays audible, and the track ducks while it plays.
    assert hum > -45, hum
    assert over_clip < over_title - 3, (over_clip, over_title)


@pytest.mark.feature("music.own-track")
def test_music_volume_sets_how_loud_your_track_plays(
    library_home: UserHome, own_track: Path, hum_with_track: RenderedRun, tmp_path
):
    quiet = _render_into(
        library_home, tmp_path, *_day(HUM_DAY, "--music", str(own_track), "--music-volume", "0.2")
    )

    loud_level, _ = loudness(hum_with_track.film, 0.5, _TITLE - 0.5, tone=TRACK_HZ)
    quiet_level, _ = loudness(quiet.film, 0.5, _TITLE - 0.5, tone=TRACK_HZ)
    assert loud_level - quiet_level > 6, (loud_level, quiet_level)


@pytest.mark.feature("audio.original-audio-off")
def test_no_original_audio_and_no_music_make_a_silent_film(
    library_home: UserHome, hum_with_track: RenderedRun, tmp_path
):
    silent = _render_into(
        library_home, tmp_path, *_day(HUM_DAY, "--no-music", "--no-original-audio")
    )
    start, end = _clip_window(library_home, silent)

    _, peak = loudness(silent.film)
    # The same clip keeps its hum when its own sound is on.
    kept, _ = loudness(
        hum_with_track.film, *_clip_window(library_home, hum_with_track), tone=HUM_HZ
    )
    assert peak < -80, peak
    assert loudness(silent.film, start, end, tone=HUM_HZ)[0] < kept - 30
    assert film_facts(silent.film).duration == pytest.approx(
        film_facts(hum_with_track.film).duration, abs=0.1
    )


@pytest.mark.feature("music.bundled-default")
@pytest.mark.usefixtures("bundled_tracks")
def test_a_failed_music_generator_falls_back_to_a_bundled_track_with_a_warning(
    immich: LibraryServer, tmp_path
):
    home = UserHome(tmp_path / "home")
    config = basic_config(immich.base_url, immich.api_key, home)
    # Nothing answers on this port, so every generation attempt fails.
    config["advanced"]["musicgen"] = {"enabled": True, "base_url": "http://127.0.0.1:9"}
    home.write_config(config)

    run = render(home, *_day(QUIET_DAY))

    assert "Optional music failed" in run.result.output
    assert "used a bundled track instead" in run.result.output
    mean, _ = loudness(run.film)
    assert mean > -40, mean


# ── canvas, transitions, captions ────────────────────────────────────────────


@pytest.mark.feature("generate.orientation-auto")
def test_auto_orientation_follows_the_kept_pictures(
    library_home: UserHome, garden_film: RenderedRun, tmp_path
):
    tall = _render_into(library_home, tmp_path, *_day(TALL_DAY, "--no-music"))
    square = cut(library_home, *_day(GARDEN_DAY, "--no-music", "--orientation", "square"))

    # Landscape clips make a landscape film, a tall picture a tall one.
    assert (film_facts(garden_film.film).width, film_facts(garden_film.film).height) == (1280, 720)
    assert (film_facts(tall.film).width, film_facts(tall.film).height) == (720, 1280)
    assert re.search(r"Canvas: (\d+)x\1 \(square\)", square.output), square.output


@pytest.fixture(scope="module")
def garden_cut_and_crossfade(library_home: UserHome, tmp_path_factory):
    cuts = _render_into(
        library_home, tmp_path_factory.mktemp("cuts"), *day_args(GARDEN_DAY), "--transition", "cut"
    )
    fades = _render_into(
        library_home,
        tmp_path_factory.mktemp("fades"),
        *day_args(GARDEN_DAY),
        "--transition",
        "crossfade",
    )
    return cuts, fades


@pytest.mark.feature("render.transitions")
def test_crossfades_overlap_the_pictures_on_whole_frames_and_cuts_do_not(
    garden_cut_and_crossfade, garden_film: RenderedRun
):
    cuts, fades = (film_facts(r.film) for r in garden_cut_and_crossfade)
    smart = film_facts(garden_film.film)

    # Every crossfade overlaps two pictures, so the faded film is the shorter one.
    assert fades.duration < cuts.duration - 0.5
    # Smart mixes fades and cuts: it never fades more than crossfade, nor less than cut.
    assert fades.duration - 0.1 <= smart.duration <= cuts.duration + 0.1
    # Whole frames: every film's frame count is its length on the 30 fps clock.
    for facts in (cuts, fades, smart):
        assert facts.frames == round(facts.duration * 30), facts


@pytest.mark.feature("captions.date-place")
def test_captions_name_the_date_and_the_city_when_they_change_and_flags_turn_them_off(
    library_home: UserHome, immich: LibraryServer, tmp_path
):
    """The garden Saturday in Brussels, a Wednesday at home, then the woods at Tervuren."""
    days = ("--start", GARDEN_DAY, "--end", "2024-06-15")
    captioned = _render_into(
        library_home, tmp_path / "on", "generate", *days, "--include-photos", "--no-music"
    )
    bare = _render_into(
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
    cities = [picture_of(s).place.city for s in shots]
    new_city = [i == 0 or city != cities[i - 1] for i, city in enumerate(cities)]
    assert cities.count("Tervuren") >= 2 and new_city.count(True) == 2, cities
    assert new_day.count(True) > new_city.count(True), new_day
    seen = [(s.at, s.day, s.seconds, city) for s, city in zip(shots, cities, strict=True)]
    # A date where the day changes and a place where the city changes, none in between.
    assert [p > 0 for p in places] == new_city, (places, seen)
    assert [d > 0 for d in dates] == new_day, (dates, seen)
    # Brussels and Tervuren are both in the home country, which stays out of the caption:
    # "BRUSSELS" alone reaches about a quarter of the way across the band, "BRUSSELS, BELGIUM"
    # past half of it. A real Immich names the fixture's places after the nearest GeoNames
    # town (Ixelles, Watermael-Boitsfort), whose names alone run longer: the widths are the
    # fake's names.
    if not immich.real:
        assert all(p < 0.4 for p in places), places
    assert film_facts(bare.film).duration == pytest.approx(film_facts(captioned.film).duration)


# ── names ────────────────────────────────────────────────────────────────────


@pytest.mark.feature("output.default-names")
def test_a_trip_film_is_named_after_its_place_and_first_day(library_home: UserHome, tmp_path):
    run = library_home.run(
        "generate",
        "--memory-type",
        "trip",
        "--year",
        "2024",
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
    assert re.fullmatch(r"trip_annecy_france_2024-06-21_[0-9a-f]{8}\.mp4", film.name), film
    assert re.fullmatch(rf"{film.stem}_\d{{8}}_\d{{6}}_[0-9a-f]{{4}}", film.parent.name)


@pytest.mark.feature("output.default-names")
def test_an_album_film_is_named_after_the_album(library_home: UserHome):
    planned = library_home.run(
        "generate",
        "--from-album",
        "The lake week",
        "--include-photos",
        "--no-music",
        "--dry-run",
        scripted_selection=True,
    )

    assert planned.returncode == 0, planned.explain()
    assert re.search(
        r"album_the_lake_week_<recipe>_<run id>/album_the_lake_week_<recipe>\.mp4", planned.stdout
    ), planned.stdout


def _pan_end_luma(tmp_path: Path, name: str, faces: list[tuple[int, int, int]]) -> float:
    """Render a still dark on the left and light on the right; the luma its pan ends on.

    `faces` are (left, top, size) boxes Immich recognised, on a 1920x1080 thumbnail.
    """
    from PIL import Image

    from immich_memories.api.models import AssetFace, AssetType, Person
    from immich_memories.config_models_render import PhotoConfig
    from immich_memories.photos.photo_pipeline import render_single_photo
    from tests.conftest import make_asset

    source = tmp_path / "halves.jpg"
    if not source.exists():
        halves = Image.new("L", (1920, 1080), 40)
        halves.paste(210, (960, 0, 1920, 1080))
        halves.convert("RGB").save(source, quality=95)
    boxes = [
        AssetFace(
            id=f"face-{n}",
            boundingBoxX1=x,
            boundingBoxY1=y,
            boundingBoxX2=x + size,
            boundingBoxY2=y + size,
            imageWidth=1920,
            imageHeight=1080,
        )
        for n, (x, y, size) in enumerate(faces)
    ]
    # One asset id for every render: the pan's start and zoom are seeded from it.
    asset = make_asset("ken-burns-still").model_copy(
        update={"type": AssetType.IMAGE, "people": [Person(id="someone", faces=boxes)]}
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
    )
    assert clip is not None
    return luma_levels(clip.path, 1.9)[0]


@pytest.mark.feature("photos.ken-burns")
def test_the_pan_heads_for_the_largest_recognised_face_or_the_centre(tmp_path):
    centre = _pan_end_luma(tmp_path, "no-face", [])
    # A small face on the dark left, the largest on the light right: the pan ends on the right.
    toward_light = _pan_end_luma(tmp_path, "largest-right", [(200, 500, 80), (1500, 400, 300)])
    # The same two faces with their sizes swapped: now it ends on the dark left.
    toward_dark = _pan_end_luma(tmp_path, "largest-left", [(200, 500, 300), (1500, 400, 80)])

    assert toward_light > centre + 5 > toward_dark + 10, (toward_dark, centre, toward_light)
