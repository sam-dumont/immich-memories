"""The review page previews the music the cut's own text asks for, and plays it (#1395).

A launch of its own: a text model and a music backend are configured, and the preview child
runs the real `music preview` with only those two remote services scripted (fake_music.py).
"""

from __future__ import annotations

import json
import signal
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from playwright.sync_api import Page, expect

from tests.e2e.conftest import (
    _REPO_ROOT,
    _build_launch_environment,
    _launch_workspace,
    _wait_for_server,
)
from tests.e2e.fake_library import THESIS
from tests.e2e.fake_music import MODEL_REQUEST, MUSIC_REQUEST
from tests.e2e.web_flow import cut_june, evidence

pytestmark = pytest.mark.e2e

_SERVER = """
import sys
from pathlib import Path

import immich_memories.config_loader as config_loader

config_path = Path(sys.argv[1])
state_dir = Path(sys.argv[2])
config_loader.Config.get_default_path = classmethod(lambda cls: config_path)
config_loader.init_config_dir = lambda: state_dir

import uvicorn

from immich_memories.web.server import create_app
from tests.e2e.fake_automation import install_hermetic_web_jobs
from tests.e2e.fake_music import MUSIC_CLI_BOOTSTRAP

app = create_app()
install_hermetic_web_jobs(app, config_path, state_dir, bootstrap=MUSIC_CLI_BOOTSTRAP)
uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[3]), log_config=None)
"""


@pytest.fixture(scope="module")
def music_launch(
    tmp_path_factory, unused_tcp_port_factory, fake_immich_server
) -> Iterator[tuple[str, Path]]:
    """The launch with a text model and a music backend configured; yields its URL and state dir."""
    workspace = _launch_workspace(tmp_path_factory.mktemp("music-preview"), fake_immich_server)
    config = yaml.safe_load(workspace.config_path.read_text())
    config["advanced"]["llm"] = {"provider": "ollama", "model": "text-reader"}
    config["advanced"]["ace_step"] = {"enabled": True}
    workspace.config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    state_dir = workspace.root / "state"
    port = unused_tcp_port_factory()
    url = f"http://127.0.0.1:{port}"
    with workspace.log_path.open("w") as log:
        proc = subprocess.Popen(
            [
                str(_REPO_ROOT / ".venv" / "bin" / "python"),
                "-c",
                _SERVER,
                str(workspace.config_path),
                str(state_dir),
                str(port),
            ],
            stdout=log,
            stderr=log,
            cwd=_REPO_ROOT,
            env=_build_launch_environment(workspace.root),
        )
        try:
            _wait_for_server(proc, base_url=url, log_path=workspace.log_path)
            yield url, state_dir
        finally:
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


def test_preview_uses_text_mood_and_plays_the_track(page: Page, music_launch) -> None:
    url, records = music_launch
    cut_june(page, url)
    panel = page.get_by_role("region", name="Render")

    panel.get_by_role("button", name="Preview a track").click()

    player = panel.locator("audio")
    expect(player).to_be_visible(timeout=120_000)
    page.wait_for_function(
        "audio => audio.readyState >= 1 && audio.duration > 0.5",
        arg=player.element_handle(),
        timeout=30_000,
    )
    expect(panel.get_by_label("The previewed track")).to_be_visible()
    request = json.loads((records / MODEL_REQUEST).read_text())
    assert request["prompt"].startswith("music-cut-text-v1")
    assert "images" not in request
    assert THESIS in request["prompt"]
    scenes = json.loads((records / MUSIC_REQUEST).read_text())
    assert "playful" in scenes[0]["mood"]
    evidence(page, "music-preview")
