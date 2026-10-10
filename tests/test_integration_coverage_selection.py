"""Real Git changes select the FFmpeg suites that measure their coverage."""

import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "changed, expected",
    [
        ("src/immich_memories/generate_music.py", {"assembly"}),
        ("src/immich_memories/processing/streaming_audio.py", {"assembly", "processing"}),
        ("src/immich_memories/web/job_routes.py", set()),
    ],
)
def test_changed_source_selects_its_real_media_suite(tmp_path, monkeypatch, changed, expected):
    # Commit hooks export these variables for the outer repository. The fixture
    # must ignore them, including when the test runs outside a commit hook.
    hook_repo = tmp_path / "hook-repository"
    monkeypatch.setenv("GIT_DIR", str(hook_repo))
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, env=env, check=True, capture_output=True, text=True
        )

    git("init")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    git("commit", "--allow-empty", "-m", "baseline")
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    source = tmp_path / changed
    source.parent.mkdir(parents=True)
    source.write_text("changed = True\n")
    git("add", changed)
    git("commit", "-m", "change")

    # WHY: replace only the expensive child suite invocation. The production
    # Make target and its Git diff/pathspec run against an actual commit.
    runner = tmp_path / "suite_runner.py"
    runner.write_text("import sys\nprint('SELECTED:' + sys.argv[1])\n")
    result = subprocess.run(
        [
            "make",
            "-f",
            str(ROOT / "Makefile"),
            "integration-coverage-for-diff",
            f"MAKE={shlex.quote(sys.executable)} {shlex.quote(str(runner))}",
        ],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    selected = {
        line.removeprefix("SELECTED:test-integration-")
        for line in result.stdout.splitlines()
        if line.startswith("SELECTED:")
    }
    assert selected == expected
    assert not hook_repo.exists()
