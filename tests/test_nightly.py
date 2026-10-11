"""The nightly build: when it builds, what it calls itself, and what it never touches."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from scripts.nightly import (
    inference_changed,
    inference_sources,
    last_nightly_commit,
    nightly_notes,
    nightly_version,
    plan,
)

ROOT = Path(__file__).resolve().parents[1]
HEAD = "a" * 40
PREVIOUS = "b" * 40


def nightly_workflow():
    workflow = yaml.safe_load((ROOT / ".github/workflows/nightly.yml").read_text())
    # PyYAML reads the GitHub Actions `on` key as a YAML 1.1 boolean.
    workflow["on"] = workflow.pop(True)
    return workflow


# --- anything new since the last nightly? ------------------------------------------


def test_a_day_without_commits_builds_nothing():
    decision = plan(head=HEAD, previous=HEAD, changed=[], sources=["src/"], force=False)
    assert decision.build is False
    assert "nothing" in decision.reason.lower()


def test_new_commits_on_main_build():
    decision = plan(head=HEAD, previous=PREVIOUS, changed=["docs/x.md"], sources=[], force=False)
    assert decision.build is True


def test_the_first_nightly_builds_everything():
    decision = plan(head=HEAD, previous=None, changed=[], sources=["src/"], force=False)
    assert decision.build is True
    assert decision.inference is True


def test_on_demand_forces_a_build_of_an_unchanged_main():
    decision = plan(head=HEAD, previous=HEAD, changed=[], sources=["src/"], force=True)
    assert decision.build is True
    # Forcing rebuilds the app; the inference images still follow their own sources.
    assert decision.inference is False


def test_the_marker_is_the_commit_named_by_the_published_release():
    body = f"Built from main.\n\nCommit: {PREVIOUS}\n"
    assert last_nightly_commit(body) == PREVIOUS
    # No release yet, or a release that never got its final body: build again.
    assert last_nightly_commit(None) is None
    assert last_nightly_commit("") is None
    assert last_nightly_commit("Commit: not-a-sha") is None


def test_the_notes_carry_the_marker_the_next_run_reads():
    notes = nightly_notes("1.0.1.dev20261011", HEAD, "nightly-20261011")
    assert last_nightly_commit(notes) == HEAD
    assert "ghcr.io/sam-dumont/immich-memories:nightly-20261011" in notes
    assert "not for production" in notes.lower()


# --- did what the inference image builds from change? -------------------------------


def test_inference_sources_come_from_the_dockerfile_copies():
    sources = inference_sources((ROOT / "docker/Dockerfile.inference").read_text())
    assert "services/inference" in sources
    assert "src/" in sources
    assert "uv.lock" in sources
    assert "docker/demucs-*-requirements.txt" in sources
    # A COPY --from another stage reads no repository file.
    assert "/app" not in sources
    assert "docker/Dockerfile.inference" in sources


@pytest.mark.parametrize(
    ("changed", "expected"),
    [
        (["services/inference/immich_memories_inference/server.py"], True),
        (["src/immich_memories/cli/__init__.py"], True),
        (["uv.lock"], True),
        (["docker/demucs-cpu-requirements.txt"], True),
        (["docker/Dockerfile.inference"], True),
        (["docs-site/docs/index.md", "tests/test_x.py", ".github/workflows/ci.yml"], False),
        (["docker/Dockerfile"], False),
        (["services/inference-extra/readme.md"], False),
        ([], False),
    ],
)
def test_inference_rebuilds_only_when_its_inputs_changed(changed, expected):
    sources = inference_sources((ROOT / "docker/Dockerfile.inference").read_text())
    assert inference_changed(changed, sources) is expected


def test_unchanged_inference_inputs_keep_the_previous_images():
    decision = plan(
        head=HEAD, previous=PREVIOUS, changed=["README.md"], sources=["src/"], force=False
    )
    assert decision.build is True
    assert decision.inference is False


# --- the version a nightly reports --------------------------------------------------


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        (["v0.103.0", "v1.0.0-rc.8", "v1.0.0-rc.7"], "1.0.0rc9.dev20261011"),
        (["v1.0.0", "v1.0.0-rc.9"], "1.0.1.dev20261011"),
        (["v1.2.3", "v0.0.0-dev.12345", "models-v9", "nightly"], "1.2.4.dev20261011"),
        ([], "0.0.1.dev20261011"),
    ],
)
def test_a_nightly_version_sorts_after_the_last_release_and_is_never_one(tags, expected):
    version = nightly_version(tags, "20261011")
    assert version == expected
    from packaging.version import Version

    parsed = Version(version)
    assert parsed.is_devrelease
    # No local `+g<sha>` part: GitHub renames release assets containing `+`, which
    # would break the wheel's file name. The commit is in the release notes.
    assert parsed.local is None


def test_every_nightly_artifact_is_stamped_with_the_nightly_version():
    """`immich-memories --version` prints the packaged version, so the build must set it."""
    jobs = nightly_workflow()["jobs"]
    version = "${{ needs.decide.outputs.version }}"
    build = next(step for step in jobs["package"]["steps"] if step.get("run") == "uv build")
    assert build["env"]["SETUPTOOLS_SCM_PRETEND_VERSION"] == version
    for job in ("app-build", "inference-build"):
        image = next(
            step for step in jobs[job]["steps"] if "push-image-digest" in step.get("uses", "")
        )
        assert f"APP_VERSION={version}" in image["with"]["build-args"], job
        assert "VCS_REF=${{ github.sha }}" in image["with"]["build-args"], job


def test_plan_command_writes_github_outputs(tmp_path):
    # WHY: a throwaway repo stands in for the checkout; gh is faked as the release catalogue.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True, env=env).strip()

    git("init", "-q")
    git("config", "user.name", "Nightly test")
    git("config", "user.email", "nightly@example.test")
    (tmp_path / "docker").mkdir()
    (tmp_path / "docker/Dockerfile.inference").write_text("FROM x\nCOPY src/ ./src/\n")
    git("add", ".")
    git("commit", "-qm", "first")
    git("tag", "v1.0.0")
    previous = git("rev-parse", "HEAD")
    (tmp_path / "README.md").write_text("hello\n")
    git("add", ".")
    git("commit", "-qm", "docs")
    head = git("rev-parse", "HEAD")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(f"#!/bin/sh\nprintf '%s' '{json.dumps({'body': f'Commit: {previous}'})}'\n")
    gh.chmod(0o700)
    output = tmp_path / "outputs"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/nightly.py"), "plan", "--date", "20261011"],
        cwd=tmp_path,
        env={
            **env,
            "PATH": f"{bin_dir}:{env['PATH']}",
            "GITHUB_SHA": head,
            "GITHUB_OUTPUT": str(output),
            "FORCE": "false",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert dict(line.split("=", 1) for line in output.read_text().splitlines()) == {
        "build": "true",
        "inference": "false",
        "version": "1.0.1.dev20261011",
        "tag": "nightly-20261011",
        "previous": previous,
    }


# --- what a nightly never touches ---------------------------------------------------


def _all_text(node) -> str:
    return json.dumps(node)


def test_nightly_runs_daily_and_on_demand():
    triggers = nightly_workflow()["on"]
    assert set(triggers) == {"schedule", "workflow_dispatch"}
    assert triggers["workflow_dispatch"]["inputs"]["force"]["type"] == "boolean"


def test_nightly_never_touches_pypi_latest_or_version_tags():
    workflow = nightly_workflow()
    text = _all_text(workflow)
    assert "pypi" not in text.lower()
    assert "make_latest" not in text
    assert ":latest" not in text
    assert "$IMAGE:latest" not in text
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            run = step.get("run", "")
            # The only tag a nightly moves is `nightly`; never a v* tag.
            assert "git tag -a v" not in run
            assert "refs/tags/v" not in run
            if "gh release create" in run:
                assert "--prerelease" in run
                assert "--latest=false" in run


def test_nightly_composite_actions_never_move_latest():
    for action in ("push-image-digest", "smoke-app-image"):
        text = (ROOT / f".github/actions/{action}/action.yml").read_text()
        assert ":latest" not in text
        assert "pypi" not in text.lower()


def test_nothing_public_happens_until_every_build_and_smoke_passed():
    jobs = nightly_workflow()["jobs"]
    dependencies = {name: set(job.get("needs", [])) for name, job in jobs.items()}

    def ancestors(name):
        return dependencies[name] | {
            ancestor for parent in dependencies[name] for ancestor in ancestors(parent)
        }

    fallible = {"package", "app-build", "app-smoke", "inference-build"}
    for public in ("manifests", "publish", "deploy-docs"):
        assert fallible <= ancestors(public), public
    assert {"manifests", "bundle"} <= ancestors("publish")
    assert "publish" in ancestors("deploy-docs")
    # The images go out by digest only; the tags move in `manifests`.
    for job in ("app-build", "inference-build"):
        assert "push-image-digest" in _all_text(jobs[job]["steps"])
    manifest_text = _all_text(jobs["manifests"])
    assert "!cancelled()" in jobs["manifests"]["if"]
    assert "needs.app-smoke.result == 'success'" in jobs["manifests"]["if"]
    assert "needs.package.result == 'success'" in jobs["manifests"]["if"]
    assert "nightly" in manifest_text


def test_every_nightly_job_waits_for_the_decision():
    jobs = nightly_workflow()["jobs"]
    for name, job in jobs.items():
        if name == "decide":
            continue
        assert "github.repository_id == '1174219883'" in job["if"], name
    for name in ("package", "app-build"):
        assert "needs.decide.outputs.build == 'true'" in jobs[name]["if"], name
    assert "needs.decide.outputs.inference == 'true'" in jobs["inference-build"]["if"]


def test_nightly_jobs_ask_for_only_what_they_use():
    workflow = nightly_workflow()
    assert workflow["permissions"] == {"contents": "read"}
    writers = {name: job.get("permissions", {}) for name, job in workflow["jobs"].items()}
    assert writers["publish"]["contents"] == "write"
    for name, permissions in writers.items():
        if name != "publish":
            assert permissions.get("contents", "read") == "read", name
    for name in ("decide", "package", "bundle", "publish"):
        assert "packages" not in writers[name], name


def _bash_major() -> int:
    result = subprocess.run(
        ["bash", "-c", "echo ${BASH_VERSINFO[0]}"], capture_output=True, text=True, check=False
    )
    return int(result.stdout.strip() or 0)


# The step runs on Ubuntu runners (bash 5); macOS ships bash 3.2, which has no `mapfile`.
@pytest.mark.skipif(_bash_major() < 4, reason="the manifests step needs bash 4 or newer")
@pytest.mark.parametrize("rebuilt", ["true", "false"])
def test_manifests_tag_nightly_and_the_day_and_never_latest(tmp_path, rebuilt):
    step = next(
        step
        for step in nightly_workflow()["jobs"]["manifests"]["steps"]
        if step.get("name") == "Tag the nightly images"
    )
    digests = tmp_path / "digests"
    for folder, digest in [
        ("digests-amd64", "1"),
        ("inference-digests-cpu-0", "2"),
        ("inference-digests-cuda-2", "3"),
    ]:
        (digests / folder).mkdir(parents=True)
        (digests / folder / (digest * 64)).touch()
    # WHY: records the tags each imagetools call would push instead of writing to GHCR.
    docker = tmp_path / "docker"
    docker.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$DOCKER_CALLS"\n')
    docker.chmod(0o755)
    calls = tmp_path / "calls"
    script = step["run"].replace("/tmp/digests", str(digests))
    subprocess.run(
        ["bash", "-e", "-c", script],
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "DOCKER_CALLS": str(calls),
            "RUNNER_TEMP": str(tmp_path),
            "APP": "ghcr.io/example/app",
            "INFERENCE": "ghcr.io/example/app/inference",
            "TAG": "nightly-20261011",
            "REBUILT": rebuilt,
        },
        check=True,
    )
    lines = calls.read_text().splitlines()
    assert len(lines) == 3  # app, inference cpu, inference cuda
    text = "\n".join(lines)
    assert "ghcr.io/example/app:nightly-20261011" in text
    assert "-t ghcr.io/example/app:nightly " in text
    assert "ghcr.io/example/app/inference:nightly-20261011-cuda" in text
    assert ":latest" not in text
    if rebuilt == "false":
        # The previous nightly's inference images get today's date, unchanged.
        assert "ghcr.io/example/app/inference:nightly-cuda" in text
        assert "-t ghcr.io/example/app/inference:nightly " not in text
