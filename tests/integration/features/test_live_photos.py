"""Live Photos in the film: motion where the clip earns it, a still where it does not, a stitch.

The fixture's Wednesday holds three Live Photos: a swing whose clip moves, a window whose clip
holds still, and a burst of three takes of one kick whose clips overlap. The scripted editor
keeps the pictures; whether each plays as motion, and how a burst joins, is decided and projected
by production code (`tests/e2e/fake_live_motion.py` says which).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.e2e.fake_library import LIVE_CLIP_SECONDS, LIVE_PICTURES
from tests.features.cli_harness import UserHome
from tests.integration.features.cuts import Shot, picture_of, story_of
from tests.integration.features.film_probe import grey_frame, luma_difference
from tests.integration.features.immich_server import LibraryServer
from tests.integration.features.library import RenderedRun, render

LIVE_DAY = "2024-06-12"
_STEP = 0.25
# Frame-to-frame change (0-255, a quarter second apart) a slow Ken Burns move stays under,
# and footage that moves clears.
_STILL_CHANGE, _MOTION_CHANGE = 8.0, 12.0


def _render(home: UserHome, directory: Path, *extra: str) -> RenderedRun:
    return render(
        home,
        "generate", "--start", LIVE_DAY, "--end", LIVE_DAY, "--include-photos", "--no-music",
        "--quiet", "--output", str(directory / "live.mp4"), *extra,
        into=directory,
    )  # fmt: skip


@pytest.fixture(scope="module")
def live_film(library_home: UserHome, tmp_path_factory) -> RenderedRun:
    return _render(library_home, tmp_path_factory.mktemp("live"))


@pytest.fixture(scope="module")
def stills_film(library_home: UserHome, tmp_path_factory) -> RenderedRun:
    return _render(library_home, tmp_path_factory.mktemp("stills"), "--no-live-photos")


def _shots(home: UserHome, run: RenderedRun) -> dict[str, Shot]:
    return {picture_of(shot).asset_id: shot for shot in story_of(home, run.run_id)}


def _inside(shot: Shot) -> list[float]:
    """Instants well inside a shot, clear of the transitions at either end."""
    first, last = shot.started + 0.6, shot.at + shot.seconds - 0.6
    return [first + _STEP * k for k in range(int((last - first) / _STEP) + 1)]


def _change(film: Path, shot: Shot) -> float:
    """Mean frame-to-frame change across a shot."""
    frames = [grey_frame(film, at) for at in _inside(shot)]
    steps = [luma_difference(a, b) for a, b in zip(frames, frames[1:], strict=False)]
    return sum(steps) / len(steps)


@pytest.mark.feature("live-photos.motion")
def test_a_live_photo_plays_as_motion_only_when_its_clip_moves(
    library_home: UserHome, live_film: RenderedRun
):
    shots = _shots(library_home, live_film)

    # One shot per Live Photo kept: the clips never play as videos of their own, and the burst's
    # other takes are inside its stitch rather than beside it.
    assert set(shots) == {p.asset_id for p in LIVE_PICTURES if p.shipped}
    assert {shot.kind for shot in shots.values()} == {"photo"}
    assert _change(live_film.film, shots["live-swing"]) > _MOTION_CHANGE
    assert _change(live_film.film, shots["live-quiet-window"]) < _STILL_CHANGE


@pytest.mark.feature("live-photos.motion")
def test_nearby_live_photos_stitch_into_one_clip_that_never_rewinds(
    library_home: UserHome, live_film: RenderedRun, immich: LibraryServer
):
    """The burst's clips are cuts of one recording; the stitch must play it forward, once."""
    kick = _shots(library_home, live_film)["live-kick-1"]
    burst = next(p for p in LIVE_PICTURES if p.motion == "burst")
    recording = immich.media / f"burst-{burst.source.stem}.mp4"
    reference = [grey_frame(recording, k / 10) for k in range(0, 60)]

    matches = []
    for at in _inside(kick):
        frame = grey_frame(live_film.film, at)
        errors = [luma_difference(frame, ref) for ref in reference]
        best = min(range(len(errors)), key=errors.__getitem__)
        matches.append((best / 10, errors[best]))

    # Longer than any one take: the three are joined.
    assert kick.seconds > LIVE_CLIP_SECONDS + 1
    # Every sampled frame is the burst's own footage, and the footage only moves forward.
    assert all(error < 12 for _, error in matches), matches
    positions = [position for position, _ in matches]
    assert all(b >= a for a, b in zip(positions, positions[1:], strict=False)), positions
    # It covers about as much of the recording as the film spends on it.
    covered = positions[-1] - positions[0]
    assert covered == pytest.approx(_inside(kick)[-1] - _inside(kick)[0], abs=0.6), positions


@pytest.mark.feature("live-photos.motion")
def test_no_live_photos_keeps_every_live_photo_a_still(
    library_home: UserHome, stills_film: RenderedRun
):
    shots = _shots(library_home, stills_film)

    assert set(shots) == {p.asset_id for p in LIVE_PICTURES if p.shipped}
    for asset_id, shot in shots.items():
        assert _change(stills_film.film, shot) < _STILL_CHANGE, asset_id
