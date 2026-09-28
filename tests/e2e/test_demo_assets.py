"""Cut the docs demo's output clip on the hermetic launch.

The demo's "and here is the video it made" scene used to play a real family
video with every face blurred. That is a privacy problem, and blurred it was
also a poor advertisement -- half the demo was unreadable mush. This renders
the same scene out of the fixture library instead: the real product, driven
through the real browser flow, over the CC0 fixture library (one household's June).

Run it with `make demo-output` after the fixture library or the renderer
changes, then re-render the demo with `make demo-ui`. It is kept out of every
automatic suite by its own marker, because it renders a second video into the
session workspace and the launch smoke counts what is in there.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageStat
from playwright.sync_api import Page, expect

from tests.e2e.cli_bootstrap import CLI_BOOTSTRAP
from tests.e2e.conftest import _REPO_ROOT, _build_launch_environment
from tests.e2e.web_flow import (
    cut_june,
    preview_without_the_first_kept,
    render,
    the_film,
)

pytestmark = [pytest.mark.e2e, pytest.mark.visual, pytest.mark.demo, pytest.mark.slow]

_PREVIEW = "output-preview.mp4"
_POSTER = "output-frame.jpg"
# Far enough in that the poster shows a picture rather than the opening title.
_POSTER_FRACTION = 0.45


@pytest.fixture
def demo_public_dir() -> Path:
    """Where the Remotion demo reads its static assets from."""
    return Path(__file__).resolve().parents[2] / "docs-site" / "remotion" / "public"


def _render_at_1080p(page: Page, launch_app_url: str) -> None:
    cut_june(page, launch_app_url)
    # The Remotion owner unticks one kept picture and previews that revision before rendering.
    preview_without_the_first_kept(page)
    # WHY no music: the demo composition lays its own track over this clip and mutes the video.
    render(page, resolution="1080p")
    expect(the_film(page)).to_be_visible(timeout=900_000)


def _poster_from(video: Path, destination: Path) -> None:
    duration = subprocess.run(  # noqa: S603
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(video),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(  # noqa: S603
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            str(round(float(duration) * _POSTER_FRACTION, 2)),
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-q:v",
            "3",
            "-update",
            "1",
            str(destination),
        ],
        check=True,
        capture_output=True,
    )


def test_cut_the_demo_output_clip(
    page: Page, launch_app_url: str, launch_workspace, demo_public_dir: Path
) -> None:
    """One real 1080p memory over the fixture library, saved for the demo to play."""
    before = set(launch_workspace.output_dir.rglob("*.mp4"))

    _render_at_1080p(page, launch_app_url)

    rendered = set(launch_workspace.output_dir.rglob("*.mp4")) - before
    assert len(rendered) == 1, f"expected one new render, found {sorted(rendered)}"
    video = rendered.pop()
    shutil.copyfile(video, demo_public_dir / _PREVIEW)
    _poster_from(video, demo_public_dir / _POSTER)


# The trip film the trip docs page plays. It is cut by the real CLI, not the
# browser: the Memory page detects trips from videos only, and the fixture's
# lake week photographs four of its seven days, so the page finds nothing to
# offer. `immich-memories generate --memory-type trip` reads every asset type.
_TRIP_CLIP = "trip-preview.mp4"
_TRIP_POSTER = "trip-map-flyover.jpg"
# Inside the opening title, which runs 3.5 s at the default: late enough that
# the map has finished travelling and both pins are on the lake, which is the
# still the trip page shows.
_FLYOVER_SECONDS = 3.0
_TRIP_MAX_BYTES = 8 * 1024 * 1024
# CRF 26 measured 6.3 MB against the 10.5 MB the renderer writes at quality
# low. The docs site serves this file to every reader of the trip page.
_TRIP_WEB_CRF = "26"


@pytest.fixture
def demo_static_dir() -> Path:
    """Where the docs site serves the demo's own videos from."""
    return Path(__file__).resolve().parents[2] / "docs-site" / "static" / "demo"


@pytest.fixture
def demo_image_dir() -> Path:
    """Where the docs site serves the demo's own stills from."""
    return Path(__file__).resolve().parents[2] / "docs-site" / "static" / "img"


def _duration_of(video: Path) -> float:
    return float(
        subprocess.run(  # noqa: S603
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(video),
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )


def _frame_at(video: Path, seconds: float, destination: Path) -> None:
    subprocess.run(  # noqa: S603
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            str(seconds),
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-q:v",
            "3",
            "-update",
            "1",
            str(destination),
        ],
        check=True,
        capture_output=True,
    )


def _encode_for_the_web(source: Path, destination: Path) -> None:
    """Re-encode the render for a docs page: same picture, a size a page can carry."""
    subprocess.run(  # noqa: S603
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-c:v",
            "libx264",
            "-crf",
            _TRIP_WEB_CRF,
            "-preset",
            "slow",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            str(destination),
        ],
        check=True,
        capture_output=True,
    )


def _trip_environment(home: Path) -> dict[str, str]:
    # WHY: a default run makes no outside call (#1037), so without these two
    # opt-ins the trip opens on its title over the first picture, not the map.
    env = _build_launch_environment(home)
    env["IMMICH_MEMORIES_NETWORK__GEOCODING"] = "true"
    env["IMMICH_MEMORIES_NETWORK__MAP_TILES"] = "true"
    return env


def _run_trip_cli(workspace, output_dir: Path) -> Path:
    """Cut the fixture's lake week through the real CLI, and return what it wrote."""
    state_dir = workspace.root / "state"
    state_dir.mkdir(exist_ok=True)
    completed = subprocess.run(  # noqa: S603
        [
            str(_REPO_ROOT / ".venv" / "bin" / "python"),
            "-c",
            CLI_BOOTSTRAP,
            str(workspace.config_path),
            str(state_dir),
            "generate",
            "--memory-type",
            "trip",
            "--year",
            "2024",
            "--trip-index",
            "1",
            "--no-music",
            "--quiet",
            "--output",
            str(output_dir / "trip.mp4"),
        ],
        cwd=_REPO_ROOT,
        env=_trip_environment(workspace.root),
        capture_output=True,
        text=True,
        timeout=1800,
    )
    rendered = sorted(output_dir.rglob("*.mp4"))
    assert completed.returncode == 0, (
        f"the trip CLI exited {completed.returncode}:\n{completed.stdout[-4000:]}"
        f"\n{completed.stderr[-4000:]}"
    )
    assert len(rendered) == 1, f"expected one trip render, found {rendered}"
    return rendered[0]


def test_cut_the_trip_memory_and_its_map(
    launch_workspace, tmp_path: Path, demo_static_dir: Path, demo_image_dir: Path
) -> None:
    """The fixture's week by the lake, cut as a trip, opening on its map fly-over.

    Needs the network: the fly-over's satellite tiles come from ArcGIS World
    Imagery and the trip's name from Nominatim, and neither has an offline
    stand-in. Without them the opening is a flat blue panel and the assertion
    on the fly-over frame is what says so.
    """
    output_dir = tmp_path / "trip-output"
    output_dir.mkdir()

    rendered = _run_trip_cli(launch_workspace, output_dir)

    clip = demo_static_dir / _TRIP_CLIP
    _encode_for_the_web(rendered, clip)
    poster = demo_image_dir / _TRIP_POSTER
    _frame_at(clip, _FLYOVER_SECONDS, poster)

    duration = _duration_of(clip)
    assert 10.0 < duration < 40.0, f"the trip film runs {duration:.1f}s"
    assert clip.stat().st_size <= _TRIP_MAX_BYTES, f"{clip.name} is {clip.stat().st_size} bytes"

    flyover = Image.open(poster).convert("L")
    assert ImageStat.Stat(flyover).mean[0] > 20, "the fly-over frame is black"
    assert ImageStat.Stat(flyover).stddev[0] > 10, "the fly-over frame is a flat panel"
