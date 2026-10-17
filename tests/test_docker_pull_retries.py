"""A registry's passing 502 costs one pull attempt, not a real-Immich leg.

The PostgreSQL legs of the real-Immich gate started their throwaway postgres:16 with a
plain `docker run`, which pulls once: one 502 from Docker Hub failed the leg (Error 125),
and a rerun passed. Every image the gate needs now arrives through scripts/docker_pull.sh,
which retries what the registry fails to serve. These drive the scripts against a stand-in
`docker` on PATH that answers 502 a given number of times before it serves the image.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
POSTGRES = "docker.io/library/postgres:16@sha256:" + "a" * 64

# A docker that has no image until a pull succeeds, and fails the first $FAILS pulls the
# way Docker Hub did. Every call is logged.
_FAKE_DOCKER = """#!/usr/bin/env bash
state=$FAKE_STATE
echo "$*" >> "$state/calls"
case "$1" in
image) [ -f "$state/pulled" ] && exit 0 || exit 1 ;;
pull)
	n=$(cat "$state/failed" 2>/dev/null || echo 0)
	if [ "$n" -lt "$FAILS" ]; then
		echo $((n + 1)) > "$state/failed"
		echo "failed to copy: unexpected status code: 502 Bad Gateway" >&2
		exit 1
	fi
	touch "$state/pulled" ;;
run) [ -f "$state/pulled" ] || { echo "docker: 502 Bad Gateway" >&2; exit 125; }
	echo container-id ;;
port) echo "127.0.0.1:55432" ;;
esac
exit 0
"""


def _env(tmp_path: Path, fails: int) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(_FAKE_DOCKER)
    docker.chmod(0o755)
    state = tmp_path / "state"
    state.mkdir()
    return {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "FAKE_STATE": str(state),
        "FAILS": str(fails),
        "DOCKER_PULL_BACKOFF": "0",
    }


def _pulls(tmp_path: Path) -> int:
    calls = (tmp_path / "state" / "calls").read_text().splitlines()
    return sum(call.startswith("pull") for call in calls)


def test_a_pull_that_meets_two_502s_retries_until_the_image_arrives(tmp_path):
    result = subprocess.run(
        [REPO / "scripts/docker_pull.sh", POSTGRES],
        env=_env(tmp_path, fails=2),
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert _pulls(tmp_path) == 3


def test_a_registry_that_never_answers_fails_after_the_last_attempt(tmp_path):
    env = _env(tmp_path, fails=99) | {"DOCKER_PULL_ATTEMPTS": "3"}
    result = subprocess.run(
        [REPO / "scripts/docker_pull.sh", POSTGRES],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 1
    assert "still missing after 3 attempts" in result.stderr
    assert _pulls(tmp_path) == 3


def test_an_image_already_here_is_never_pulled(tmp_path):
    env = _env(tmp_path, fails=0)
    (tmp_path / "state" / "pulled").touch()
    result = subprocess.run(
        [REPO / "scripts/docker_pull.sh", POSTGRES], env=env, capture_output=True, timeout=60
    )

    assert result.returncode == 0
    assert _pulls(tmp_path) == 0


def test_the_throwaway_postgres_survives_a_502_on_its_image(tmp_path):
    env = {k: v for k, v in _env(tmp_path, fails=1).items() if k != "STORE_URL"}
    result = subprocess.run(
        [
            REPO / "scripts/with_throwaway_postgres.sh",
            "STORE_URL",
            POSTGRES,
            "--",
            "sh",
            "-c",
            'echo "store at $STORE_URL"',
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "store at postgresql://postgres:store-test@127.0.0.1:55432/postgres" in result.stdout
    assert _pulls(tmp_path) == 2
