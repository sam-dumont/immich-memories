"""`generate --keep-intermediates` keeps the cut segments in the run folder (#2346).

The terminal cut of the fixture month, with the flag on. Each segment the film was cut
from must be in the run folder's `.intermediates`, and still play.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests.e2e.cli_bootstrap import CLI_BOOTSTRAP
from tests.e2e.conftest import _build_launch_environment, _owned_workspace
from tests.e2e.fake_library import MONTH, YEAR

pytestmark = pytest.mark.e2e

_ROOT = Path(__file__).resolve().parents[2]


def _video_streams(path: Path) -> list[dict]:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return [s for s in json.loads(probe.stdout)["streams"] if s["codec_type"] == "video"]


@pytest.mark.feature("generate.keep-intermediates")
def test_keep_intermediates_leaves_the_cut_segments_in_the_run_folder(
    tmp_path_factory: pytest.TempPathFactory, fake_immich_server
) -> None:
    workspace_owner = _owned_workspace(tmp_path_factory.mktemp("keep"), fake_immich_server)
    workspace = next(workspace_owner)
    try:
        result = subprocess.run(
            [
                str(_ROOT / ".venv/bin/python"),
                "-c",
                CLI_BOOTSTRAP,
                str(workspace.config_path),
                str(workspace.root / "state"),
                "generate",
                "--memory-type",
                "monthly_highlights",
                "--year",
                str(YEAR),
                "--month",
                str(MONTH),
                "--no-music",
                "--quiet",
                "--keep-intermediates",
            ],
            cwd=_ROOT,
            env=_build_launch_environment(workspace.root),
            capture_output=True,
            text=True,
            timeout=600,
        )
        assert result.returncode == 0, result.stdout + result.stderr

        # The film sits at the top of its run folder; kept work lives in dot folders below.
        films = list(workspace.output_dir.glob("*/*.mp4"))
        assert len(films) == 1, films
        segments = sorted((films[0].parent / ".intermediates").glob("*.mp4"))
        # The month's cut holds several of the library's videos; each was cut to a segment.
        assert len(segments) >= 2, segments
        assert all(_video_streams(segment) for segment in segments)
    finally:
        next(workspace_owner, None)
