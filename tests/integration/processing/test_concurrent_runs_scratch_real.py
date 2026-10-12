"""Two runs that cut the same video at once each keep their own segments (#2452).

Both runs read the source from the same place (the shared video cache) and cut the
same window. The first to finish cleans up its segments; the other must still have
all of its own when it assembles.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from immich_memories.config_loader import Config
from immich_memories.generate import GenerationParams
from immich_memories.generate_clips import cleanup_temp_clips, extract_clips
from immich_memories.processing.clip_validation import validate_clips
from immich_memories.processing.output_canvas import OutputCanvas
from tests.conftest import make_clip

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def cached_video(tmp_path_factory) -> Path:
    """The one copy of the original both runs read, as the video cache holds it."""
    path = tmp_path_factory.mktemp("video-cache") / "garden-table.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=4",
            "-c:v", "libx264", "-preset", "ultrafast", "-g", "15", str(path),
        ],
        check=True,
        timeout=60,
    )  # fmt: skip
    return path


def _run(cached_video: Path, run_dir: Path) -> list:
    clip = make_clip("garden-table", width=640, height=360, duration=4)
    clip.asset.file_created_at = datetime(2024, 6, 8, 12, tzinfo=UTC)
    clip.local_path = str(cached_video)
    config = Config()
    config.hardware.enabled = False
    params = GenerationParams(
        clips=[clip],
        output_path=run_dir / "film.mp4",
        config=config,
        output_canvas=OutputCanvas(640, 360, "landscape"),
        clip_segments={"garden-table": (0.5, 3.0)},
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    return extract_clips(params, None, run_dir)


def test_the_run_that_finishes_first_leaves_the_other_runs_segments(tmp_path, cached_video):
    first = _run(cached_video, tmp_path / "first")
    second = _run(cached_video, tmp_path / "second")

    cleanup_temp_clips(first)  # the first run is done and tidies up
    kept, dropped = validate_clips(second)

    assert [clip.asset_id for clip in dropped] == []
    assert [clip.asset_id for clip in kept] == ["garden-table"]
    assert first[0].path != second[0].path
