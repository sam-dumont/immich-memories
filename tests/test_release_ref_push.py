"""Release tags and releases are written with the CI app's token, and only by the steps that write.

GitHub refuses a ref GITHUB_TOKEN writes when the move brings workflow files main no
longer has (#2615), so the version tag and the nightly tag go out with a token the CI
GitHub App mints; the GitHub Release and the nightly prerelease use it too, so the release
job's GITHUB_TOKEN only reads. These tests run the push script against a local remote and
check the token stays inside the steps that write.
"""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "push_release_ref.sh"
CANARY = "canary-value-that-must-never-be-printed"


def _git(cwd, *args, env):
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """A clone with two commits and a bare `origin` holding a `nightly` tag at the first."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.pop("GITHUB_ACTIONS", None)
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    _git(tmp_path, "init", "-q", "--bare", str(origin), env=env)
    _git(tmp_path, "init", "-q", str(work), env=env)
    for args in (
        ("config", "user.name", "Release test"),
        ("config", "user.email", "release@example.test"),
        ("remote", "add", "origin", str(origin)),
        ("commit", "--allow-empty", "-qm", "fix: first"),
        ("tag", "nightly"),
        ("push", "-q", "origin", "refs/tags/nightly"),
        ("commit", "--allow-empty", "-qm", "fix: second"),
        ("tag", "-f", "nightly"),
    ):
        _git(work, *args, env=env)
    return work, origin, env


def _push(work, env, *args):
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _remote_tag(origin, env, name):
    return subprocess.run(
        ["git", "rev-parse", "-q", "--verify", f"refs/tags/{name}"],
        cwd=origin,
        env=env,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_a_missing_token_stops_before_any_push_and_names_the_secret(repo):
    work, origin, env = repo
    before = _remote_tag(origin, env, "nightly")

    result = _push(work, env, "--force", "refs/tags/nightly")

    assert result.returncode == 1
    assert "RELEASE_TAG_TOKEN is missing" in result.stdout
    assert _remote_tag(origin, env, "nightly") == before


def test_the_nightly_tag_moves_and_the_token_is_never_printed(repo):
    work, origin, env = repo

    result = _push(work, {**env, "RELEASE_TAG_TOKEN": CANARY}, "--force", "refs/tags/nightly")

    assert result.returncode == 0, result.stderr
    assert _remote_tag(origin, env, "nightly") == _git(work, "rev-parse", "HEAD", env=env)
    assert CANARY not in result.stdout + result.stderr


def test_a_new_version_tag_is_pushed(repo):
    work, origin, env = repo
    _git(work, "tag", "-a", "v1.2.4", "-m", "Release v1.2.4", env=env)

    result = _push(work, {**env, "RELEASE_TAG_TOKEN": CANARY}, "refs/tags/v1.2.4")

    assert result.returncode == 0, result.stderr
    assert _remote_tag(origin, env, "v1.2.4")


def test_a_refused_push_names_the_app_without_printing_the_token(repo):
    work, origin, env = repo
    # WHY: a moved tag without --force is refused, standing in for GitHub refusing an
    # expired token or one without Workflows write.
    result = _push(work, {**env, "RELEASE_TAG_TOKEN": CANARY}, "refs/tags/nightly")

    assert result.returncode == 1
    assert "immich-memories-ci-bot" in result.stdout
    assert CANARY not in result.stdout + result.stderr


def _steps_using_the_token():
    found = []
    for path in sorted((ROOT / ".github").rglob("*.yml")):
        if "RELEASE_TAG_TOKEN" not in path.read_text():
            continue
        workflow = yaml.safe_load(path.read_text())
        for job_name, job in (workflow.get("jobs") or {}).items():
            for step in job.get("steps", []):
                if "RELEASE_TAG_TOKEN" in yaml.safe_dump(step):
                    found.append((path.name, job_name, step.get("name")))
    return found


def test_only_the_two_ref_writing_steps_see_the_token():
    assert _steps_using_the_token() == [
        ("release.yml", "release", "Push release tag"),
        ("release.yml", "release", "Move the nightly tag to this commit"),
    ]


def test_the_release_job_checkout_keeps_no_credentials():
    checkout = next(
        step for step in _release_steps() if step.get("uses", "").startswith("actions/checkout@")
    )
    assert checkout["with"]["persist-credentials"] is False


def _release_steps():
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    return workflow["jobs"]["release"]["steps"]


_MINTED = "${{ steps.release-token.outputs.token }}"
# Every step of the release job that writes a ref or a release, in order.
_WRITERS = [
    "Push release tag",
    "Create GitHub Release",
    "Move the nightly tag to this commit",
    "Replace the nightly prerelease",
]


def test_the_token_is_minted_by_the_ci_app_for_this_repository_only():
    """No stored token: the release job mints a one-hour app token before its first write."""
    steps = _release_steps()
    names = [step.get("name") for step in steps]
    mint = steps[names.index("Mint the release token")]
    assert mint["id"] == "release-token"
    assert mint["uses"].startswith("actions/create-github-app-token@")
    assert mint["with"]["repositories"] == "immich-memories"
    assert {key for key in mint["with"] if key.startswith("permission-")} == {
        "permission-contents",
        "permission-workflows",
    }
    assert mint["with"]["permission-contents"] == "write"
    assert mint["with"]["permission-workflows"] == "write"
    assert all(names.index("Mint the release token") < names.index(name) for name in _WRITERS)
    for name in ("Push release tag", "Move the nightly tag to this commit"):
        env = steps[names.index(name)]["env"]
        # The minted token's output, never a stored secret.
        assert env["RELEASE_TAG_TOKEN"] == _MINTED


def test_only_the_writing_steps_see_the_minted_token():
    seen = [step.get("name") for step in _release_steps() if "steps.release-token" in str(step)]
    assert seen == _WRITERS


def test_the_releases_are_written_with_the_minted_token():
    steps = {step.get("name"): step for step in _release_steps()}
    assert steps["Create GitHub Release"]["with"]["token"] == _MINTED
    assert steps["Replace the nightly prerelease"]["env"]["GH_TOKEN"] == _MINTED


def test_the_release_job_github_token_only_reads():
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    assert workflow["jobs"]["release"]["permissions"] == {"contents": "read"}
    # The one step that still hands GITHUB_TOKEN to a tool asks whether a release exists.
    readers = [
        step.get("name")
        for step in workflow["jobs"]["release"]["steps"]
        if "secrets.GITHUB_TOKEN" in str(step) or "github.token" in str(step)
    ]
    assert readers == ["Push release tag"]


def test_no_workflow_reads_a_stored_release_token():
    for path in sorted((ROOT / ".github").rglob("*.yml")):
        assert "secrets.RELEASE_TAG_TOKEN" not in path.read_text(), path.name
