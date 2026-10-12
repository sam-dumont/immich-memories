"""The film's sound: your own track, its volume, the clips' own sound and the bundled tracks.

Each test listens to the finished film (loudness at the track's and the clip's own pitch).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.features.cli_harness import UserHome, basic_config, film_facts
from tests.integration.features.cuts import story_of
from tests.integration.features.film_probe import (
    loudness,
)
from tests.integration.features.immich_server import LibraryServer
from tests.integration.features.library import (
    QUIET_DAY,
    RenderedRun,
    one_day,
    render,
    render_into,
    the_day_only,
)

# A day of one clip with its own sound recorded (a phone's recording) and no stills.
HUM_DAY = the_day_only(lambda p: p.is_video and p.voiced)
# The clip's sound is a real recording (water, wind): measured in the band a hum would sit in.
HUM_HZ = 220
TRACK_HZ = 660
_TITLE = 3.0


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
    run = render_into(library_home, tmp_path, *one_day(QUIET_DAY, "--duration", "60"))
    facts = film_facts(run.film)

    assert facts.duration < 30
    mean, _ = loudness(run.film)
    assert mean > -40, mean
    assert "Optional music failed" not in run.result.output


@pytest.fixture(scope="module")
def hum_with_track(library_home: UserHome, own_track: Path, tmp_path_factory) -> RenderedRun:
    directory = tmp_path_factory.mktemp("hum-loud")
    return render_into(
        library_home,
        directory,
        *one_day(HUM_DAY, "--music", str(own_track), "--music-volume", "0.8"),
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
    quiet = render_into(
        library_home,
        tmp_path,
        *one_day(HUM_DAY, "--music", str(own_track), "--music-volume", "0.2"),
    )

    loud_level, _ = loudness(hum_with_track.film, 0.5, _TITLE - 0.5, tone=TRACK_HZ)
    quiet_level, _ = loudness(quiet.film, 0.5, _TITLE - 0.5, tone=TRACK_HZ)
    assert loud_level - quiet_level > 6, (loud_level, quiet_level)


@pytest.mark.feature("audio.original-audio-off")
def test_no_original_audio_and_no_music_make_a_silent_film(
    library_home: UserHome, hum_with_track: RenderedRun, tmp_path
):
    silent = render_into(
        library_home, tmp_path, *one_day(HUM_DAY, "--no-music", "--no-original-audio")
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

    run = render(home, *one_day(QUIET_DAY))

    assert "Optional music failed" in run.result.output
    assert "used a bundled track instead" in run.result.output
    mean, _ = loudness(run.film)
    assert mean > -40, mean
