"""A saved cut rendered again with other output options, a finished film uploaded afterwards,
and a privacy film's names.

Each runs the real CLI in a sealed home. A saved revision is made the way the browser makes
one: `immich-memories ui` is asked over HTTP to keep the owner's edit.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from tests.e2e.fake_immich import ALBUM_ID, ALBUMS, FakeImmichServer
from tests.features.cli_harness import (
    RUN_ID,
    OutboundTrap,
    UserHome,
    basic_config,
    film_facts,
    films_under,
)
from tests.features.served_app import served_app
from tests.integration.features.immich_server import LibraryServer
from tests.integration.features.library import (
    DEPARTURE_DAY,
    QUIET_DAY,
    day_args,
    render,
    shipped_on,
)

_KEPT_RUN = re.compile(r"runs render (\d{8}_\d{6}_[0-9a-f]{4})")


def _saved_cut(home: UserHome, day: str) -> str:
    """`generate --no-render` over one day: the id of the cut it kept."""
    result = home.run(*day_args(day), "--no-render", scripted_selection=True)
    assert result.returncode == 0, result.explain()
    found = _KEPT_RUN.findall(result.output)
    assert found, result.explain()
    return found[0]


def _loudest_db(film: Path) -> float:
    """The film's peak audio level in dB; -91 for digital silence or no audio at all."""
    if not film_facts(film).has_audio:
        return -91.0
    detected = subprocess.run(  # noqa: S603 -- fixed ffmpeg argv
        ["ffmpeg", "-v", "info", "-i", str(film), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=True,
    ).stderr
    peak = re.search(r"max_volume: (-?[\d.]+|-inf) dB", detected)
    assert peak, detected[-2000:]
    return -91.0 if peak.group(1) == "-inf" else float(peak.group(1))


def _shot_lines(story: str) -> list[str]:
    """The shot lines of a `runs story` printout: timecode, day, kind."""
    return re.findall(r"^\s+\d+:\d\d\s+\d{4}-\d\d-\d\d\s+(?:photo|video)\b.*$", story, re.M)


# ── runs render: a saved revision, other output options, the same pictures ───


@pytest.fixture
def own_home(tmp_path: Path, immich: LibraryServer, outbound_trap: OutboundTrap) -> UserHome:
    home = UserHome(tmp_path / "home", extra_env=tuple(outbound_trap.env().items()))
    home.write_config(basic_config(immich.base_url, immich.api_key, home))
    return home


@pytest.mark.feature("runs.render-options")
def test_runs_render_takes_a_saved_revision_and_changes_only_the_output(
    own_home: UserHome, immich: LibraryServer, tmp_path: Path
):
    home = own_home
    cut_id = _saved_cut(home, DEPARTURE_DAY)
    # The owner takes the last still out in the browser editor: revision 1.
    removed = shipped_on(DEPARTURE_DAY)[-1]
    assert not removed.is_video
    home.turn_sign_in_off()  # this test is about revisions, not sign-in
    with served_app(home) as app, app.client() as browser:
        saved = browser.post(
            f"/api/v1/runs/{cut_id}/revisions", json={"removed": [immich.id_of(removed.asset_id)]}
        )
    assert saved.status_code == 201, saved.text
    assert saved.json()["number"] == 1
    progress = tmp_path / "progress.json"
    before = set(films_under(home.videos))

    result = home.run(
        "--verbose",
        "runs",
        "render",
        cut_id,
        "--revision",
        "1",
        "--title",
        "Options Title",
        "--subtitle",
        "Kept as it was cut",
        "--resolution",
        "1080p",
        "--orientation",
        "portrait",
        "--scale-mode",
        "fit",
        "--format",
        "h265",
        "--quality",
        "low",
        "--transition",
        "cut",
        "--fade-color",
        "white",
        "--title-style",
        "modern_warm",
        "--no-add-date",
        "--no-add-place",
        "--no-music",
        "--no-original-audio",
        "--progress-file",
        str(progress),
    )

    assert result.returncode == 0, result.explain()
    added = [film for film in films_under(home.videos) if film not in before]
    assert len(added) == 1, result.explain()
    film = film_facts(added[0])
    assert (film.codec, film.width, film.height) == ("hevc", 1080, 1920)
    render_id = RUN_ID.findall(added[0].parent.name)[-1]
    assert render_id != cut_id
    # The pictures are the revision's: the cut's, less the one the owner took out.
    for picture in shipped_on(DEPARTURE_DAY):
        why = home.run("runs", "why", immich.id_of(picture.asset_id), "--run", render_id)
        assert why.returncode == 0, why.explain()
        took_out = "you removed it before rendering" in why.output
        assert took_out == (picture is removed), (picture.asset_id, why.output)
    # `runs story` prints the cut the film was rendered from: the revision, one still short.
    cut_story = home.run("runs", "story", cut_id)
    film_story = home.run("runs", "story", render_id)
    assert film_story.returncode == 0, film_story.explain()
    shots = len(shipped_on(DEPARTURE_DAY))
    assert f"{shots} pictures" in cut_story.output, cut_story.explain()
    assert f"{shots - 1} pictures" in film_story.output, film_story.explain()
    assert len(_shot_lines(film_story.output)) == len(_shot_lines(cut_story.output)) - 1
    shown = home.run("runs", "show", render_id)
    assert re.search(r"Title From\s*│\s*override", shown.stdout), shown.explain()
    # No date or place caption is drawn onto any shot, and no sound is left.
    assert "drawtext=" not in result.output
    assert _loudest_db(added[0]) < -60
    assert json.loads(progress.read_text()), "the progress file holds the render's progress"


# ── runs upload ──────────────────────────────────────────────────────────────


@pytest.mark.feature("runs.upload")
@pytest.mark.fake_immich_only(
    "reads the film from the upload log of a fake Immich that holds no other test's upload"
)
def test_runs_upload_sends_the_film_on_disk_into_the_album_and_frees_it(
    tmp_path: Path, delivery_immich: FakeImmichServer, outbound_trap: OutboundTrap
):
    home = UserHome(tmp_path / "home", extra_env=tuple(outbound_trap.env().items()))
    home.write_config(basic_config(delivery_immich.base_url, delivery_immich.api_key, home))
    cut_id = _saved_cut(home, QUIET_DAY)
    film = render(home, *day_args(QUIET_DAY))
    album = ALBUMS[0]["albumName"]

    never_rendered = home.run("runs", "upload", cut_id)
    uploaded = home.run("runs", "upload", film.run_id, "--album", album)

    assert never_rendered.returncode != 0, never_rendered.explain()
    assert "runs render" in never_rendered.output, never_rendered.explain()
    assert uploaded.returncode == 0, uploaded.explain()
    assert [(u.filename, u.content_type) for u in delivery_immich.uploads] == [
        (film.film.name, "video/mp4")
    ]
    assert ("PUT", f"/api/albums/{ALBUM_ID}/assets") in delivery_immich.wire.requests
    # Immich confirmed it, so the local copy is gone, and the command said so.
    assert not film.film.exists()
    assert re.search(r"remov|delet", uploaded.output, re.I), uploaded.explain()


# ── privacy mode: the names the film shows ───────────────────────────────────

_OPENING_TITLE = re.compile(r"Opening title from \w+: '([^']*)'")


@pytest.mark.feature("privacy.privacy-mode-names")
def test_privacy_mode_shows_a_stand_in_for_the_name_the_title_would_show(
    own_home: UserHome, tmp_path: Path
):
    film_of_charlie = (
        "--verbose",
        "generate",
        "--memory-type",
        "person_spotlight",
        "--person",
        "Charlie",
        "--start",
        DEPARTURE_DAY,
        "--end",
        DEPARTURE_DAY,
        "--include-photos",
        "--no-music",
    )

    plain = render(
        own_home, *film_of_charlie, "--output", str(tmp_path / "a" / "f.mp4"), into=tmp_path / "a"
    )
    private = render(
        own_home,
        *film_of_charlie,
        "--privacy-mode",
        "--output",
        str(tmp_path / "b" / "f.mp4"),
        into=tmp_path / "b",
    )

    # The title the opening card is drawn from, as the render hands it to the title renderer.
    plain_title = _OPENING_TITLE.findall(plain.result.output)
    private_title = _OPENING_TITLE.findall(private.result.output)
    assert plain_title and "Charlie" in plain_title[0], plain.result.explain()
    assert private_title, private.result.explain()
    assert "Charlie" not in private_title[0]
    # The rest of the title stays: only the name was swapped, for one name.
    stand_in = private_title[0].split(" · ")[0]
    assert stand_in and private_title[0] == plain_title[0].replace("Charlie", stand_in)
    assert film_facts(private.film).duration > 1
