"""The nightly build: when it builds, what it calls itself, and what it never touches.

The nightly is the release process run on channel `nightly`: nightly.yml decides and
calls release.yml. These tests hold both halves of that, and every nightly-only rule.
"""

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
    last_nightly_tag,
    nightly_notes,
    nightly_version,
    plan,
)

ROOT = Path(__file__).resolve().parents[1]
HEAD = "a" * 40
PREVIOUS = "b" * 40


def _workflow(name):
    workflow = yaml.safe_load((ROOT / ".github/workflows" / name).read_text())
    # PyYAML reads the GitHub Actions `on` key as a YAML 1.1 boolean.
    workflow["on"] = workflow.pop(True)
    return workflow


def nightly_workflow():
    return _workflow("nightly.yml")


def release_workflow():
    return _workflow("release.yml")


def _step(job, name):
    return next(
        step for step in release_workflow()["jobs"][job]["steps"] if step.get("name") == name
    )


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


def test_the_dev_docs_read_the_nightly_tag_from_its_notes():
    """The dev docs pin the setup files to the nightly they were built from."""
    assert last_nightly_tag(nightly_notes("1.0.1.dev20261011", HEAD, "nightly-20261011")) == (
        "nightly-20261011"
    )
    assert last_nightly_tag(None) is None
    assert last_nightly_tag("Commit: " + HEAD) is None


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


# --- one process: the nightly is the release workflow on channel `nightly` ----------

NIGHTLY = "inputs.channel == 'nightly'"
NOT_NIGHTLY = "inputs.channel != 'nightly'"


def test_nightly_runs_daily_and_on_demand():
    triggers = nightly_workflow()["on"]
    assert set(triggers) == {"schedule", "workflow_dispatch"}
    assert triggers["workflow_dispatch"]["inputs"]["force"]["type"] == "boolean"


def test_the_nightly_decides_then_calls_the_release_process():
    jobs = nightly_workflow()["jobs"]
    assert set(jobs) == {"decide", "release"}
    call = jobs["release"]
    assert call["uses"] == "./.github/workflows/release.yml"
    assert call["needs"] == ["decide"]
    assert "needs.decide.outputs.build == 'true'" in call["if"]
    assert "github.repository_id == '1174219883'" in call["if"]
    assert call["with"] == {
        "channel": "nightly",
        "nightly_version": "${{ needs.decide.outputs.version }}",
        "nightly_tag": "${{ needs.decide.outputs.tag }}",
        "rebuild_inference": "${{ needs.decide.outputs.inference == 'true' }}",
    }
    # Nothing is built here: no job besides the decision has steps of its own.
    assert "steps" not in call


def test_the_release_can_be_called_with_every_dispatch_input_and_the_nightly_ones():
    triggers = release_workflow()["on"]
    dispatch = set(triggers["workflow_dispatch"]["inputs"])
    call = triggers["workflow_call"]["inputs"]
    assert dispatch <= set(call)
    assert {"nightly_version", "nightly_tag", "rebuild_inference"} <= set(call)
    assert call["channel"]["default"] == "stable"
    # A dispatch offers stable and rc; only nightly.yml, after its check, runs a nightly.
    assert triggers["workflow_dispatch"]["inputs"]["channel"]["options"] == ["stable", "rc"]


def test_a_nightly_skips_only_the_package_index():
    """Every other release job runs for a nightly too, CI and the Immich gate included."""
    jobs = release_workflow()["jobs"]
    skipped = {
        name
        for name, job in jobs.items()
        if f"github.repository_id == '1174219883' && {NOT_NIGHTLY} &&" in job.get("if", "")
    }
    assert skipped == {"pypi-publish", "pypi-publish-music"}
    # Main and the release run every gate: nothing after CI accepts its skip.
    for name in ("package", "release", "docker-build", "inference-build", "inference-manifest"):
        condition = " ".join(jobs[name]["if"].split())
        assert (
            "(needs.ci.result == 'success' && needs.immich-gate.result == 'success')" in condition
        ), name
        assert "needs.ci.result == 'skipped'" not in condition, name
    for gate in ("ci", "immich-gate"):
        assert NOT_NIGHTLY not in jobs[gate]["if"], gate
    assert jobs["ci"]["uses"] == "./.github/workflows/ci.yml"
    assert jobs["immich-gate"]["uses"] == "./.github/workflows/immich-gate.yml"
    docs = " ".join(jobs["deploy-docs"]["if"].split())
    assert "needs.release.result == 'success'" in docs
    assert "(inputs.channel == 'nightly' && needs.pypi-publish.result == 'skipped')" in docs


def test_every_nightly_job_after_ci_states_its_own_status_check():
    """GitHub's implicit `success()` reads every ancestor, skipped ones included.

    When a nightly skipped `ci`, a job after it whose condition named no status function
    was skipped with it, and so was everything after that: a nightly reported success and
    published nothing. An app-only or inference-only release still skips jobs upstream.
    """
    jobs = release_workflow()["jobs"]

    def ancestors(name: str) -> set[str]:
        found: set[str] = set()
        for parent in jobs[name].get("needs") or []:
            found |= {parent} | ancestors(parent)
        return found

    implicit = {
        name
        for name, job in jobs.items()
        if "ci" in ancestors(name)
        and f"{NOT_NIGHTLY} &&" not in job.get("if", "")
        and not any(check in job.get("if", "") for check in ("!cancelled()", "always()"))
    }

    assert implicit == set()


def test_a_nightly_has_no_approval_environment():
    environment = release_workflow()["jobs"]["docker-build"]["environment"]["name"]
    # `a && b || ''`: for a nightly the name is empty, which means no environment.
    assert environment.startswith("${{ inputs.channel != 'nightly' && (")
    assert environment.endswith("|| '' }}")
    assert "production-major" in environment


def test_inference_images_rebuild_only_when_the_nightly_says_so():
    jobs = release_workflow()["jobs"]
    assert (
        "(inputs.channel != 'nightly' || inputs.rebuild_inference)" in jobs["inference-build"]["if"]
    )
    for name in ("inference-manifest", "docker-manifest"):
        condition = " ".join(jobs[name]["if"].split())
        assert (
            "(inputs.channel == 'nightly' && !inputs.rebuild_inference && "
            "needs.inference-build.result == 'skipped')" in condition
        ), name


def _name_the_nightly(tmp_path, **overrides):
    output = tmp_path / "outputs"
    env = {
        **os.environ,
        "GITHUB_OUTPUT": str(output),
        "NIGHTLY_VERSION": "1.0.0rc9.dev20261011",
        "NIGHTLY_TAG": "nightly-20261011",
        "DRY_RUN": "false",
        "APP_ONLY": "false",
        "INFERENCE_ONLY": "false",
        **overrides,
    }
    step = _step("analyze", "Name the nightly")
    assert step["if"] == NIGHTLY
    result = subprocess.run(
        ["bash", "-e", "-c", step["run"]], env=env, capture_output=True, text=True, check=False
    )
    lines = output.read_text().splitlines() if output.exists() else []
    return result.returncode, lines


def test_a_nightly_is_named_by_its_decision_not_by_a_version_series(tmp_path):
    returncode, lines = _name_the_nightly(tmp_path)
    assert returncode == 0
    assert lines == [
        "should_release=true",
        "next_version=1.0.0rc9.dev20261011",
        "release_type=nightly",
        "prerelease=true",
        "previous_tag=",
        "image_tag=nightly-20261011",
    ]
    analyze = release_workflow()["jobs"]["analyze"]
    series = next(step for step in analyze["steps"] if step.get("id") == "analyze")
    assert series["if"] == NOT_NIGHTLY
    assert analyze["outputs"]["image_tag"] == (
        "${{ steps.nightly.outputs.image_tag || steps.analyze.outputs.next_version }}"
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"DRY_RUN": "true"},
        {"APP_ONLY": "true"},
        {"INFERENCE_ONLY": "true"},
        {"NIGHTLY_VERSION": "1.0.0"},
        {"NIGHTLY_VERSION": ""},
        {"NIGHTLY_TAG": "latest"},
        {"NIGHTLY_TAG": "v1.0.0"},
    ],
)
def test_a_nightly_refuses_release_modes_and_foreign_names(tmp_path, overrides):
    returncode, lines = _name_the_nightly(tmp_path, **overrides)
    assert returncode != 0
    assert lines == []


def test_every_nightly_artifact_is_stamped_with_the_nightly_version():
    """`immich-memories --version` prints the packaged version, so the build must set it."""
    jobs = release_workflow()["jobs"]
    version = "${{ needs.analyze.outputs.next_version }}"
    build = next(step for step in jobs["package"]["steps"] if step.get("run") == "uv build")
    assert build["env"]["SETUPTOOLS_SCM_PRETEND_VERSION"] == version
    for job in ("docker-build", "inference-build"):
        image = next(
            step for step in jobs[job]["steps"] if "push-image-digest" in step.get("uses", "")
        )
        assert f"APP_VERSION={version}" in image["with"]["build-args"], job
        assert "VCS_REF=${{ github.sha }}" in image["with"]["build-args"], job
    # The setup files pin the dated image tag, which for a release is its version.
    bundle = _step("deployment-bundle", "Package deployment files")
    assert bundle["env"]["VERSION"] == "${{ needs.analyze.outputs.image_tag }}"


def test_the_nightly_notes_carry_the_marker(tmp_path):
    step = _step("package", "Write the nightly notes")
    assert step["if"] == NIGHTLY
    assert _step("package", "Generate changelog")["if"] == NOT_NIGHTLY
    script = step["run"].replace("scripts/nightly.py", str(ROOT / "scripts/nightly.py"))
    subprocess.run(
        ["bash", "-e", "-c", script],
        cwd=tmp_path,
        env={
            **os.environ,
            "NEXT_VERSION": "1.0.1.dev20261011",
            "IMAGE_TAG": "nightly-20261011",
            "GITHUB_SHA": HEAD,
        },
        check=True,
    )
    notes = (tmp_path / "release_notes.md").read_text()
    assert last_nightly_commit(notes) == HEAD
    assert "nightly-20261011" in notes


def test_a_nightly_moves_only_the_nightly_tag_and_its_rolling_prerelease():
    release = release_workflow()["jobs"]["release"]
    by_name = {step.get("name"): step for step in release["steps"]}
    # The version tag and the versioned GitHub Release are the stable and rc channels'.
    assert by_name["Push release tag"]["if"] == NOT_NIGHTLY
    assert by_name["Create GitHub Release"]["if"] == NOT_NIGHTLY
    tag = by_name["Move the nightly tag to this commit"]
    assert tag["if"] == NIGHTLY
    assert "refs/tags/nightly" in tag["run"]
    assert "refs/tags/v" not in tag["run"]
    assert "git tag -a" not in tag["run"]
    publish = by_name["Replace the nightly prerelease"]
    assert publish["if"] == NIGHTLY
    assert "gh release create nightly" in publish["run"]
    assert "--prerelease" in publish["run"]
    assert "--latest=false" in publish["run"]
    assert "--notes-file release_notes.md" in publish["run"]
    # The same files a release attaches: wheel, sdist, provenance, setup files.
    for files in ("dist/*.whl", "attestations/*.intoto.jsonl", "deployment-assets/*"):
        assert files in publish["run"]
    nightly_only = [step for step in release["steps"] if step.get("if") == NIGHTLY]
    assert "pypi" not in json.dumps(nightly_only).lower()


def test_nightly_composite_actions_never_move_latest():
    for action in ("push-image-digest", "smoke-app-image"):
        text = (ROOT / f".github/actions/{action}/action.yml").read_text()
        assert ":latest" not in text
        assert "pypi" not in text.lower()


def test_the_nightly_grants_only_what_the_release_jobs_ask_for():
    workflow = nightly_workflow()
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["decide"]["permissions"] == {"contents": "read"}
    # A called workflow cannot exceed its caller, so the call grants their union.
    asked = {}
    for name in ("release.yml", "ci.yml", "immich-gate.yml", "docs.yml"):
        for job in _workflow(name)["jobs"].values():
            for scope, level in (job.get("permissions") or {}).items():
                if level == "write" or asked.get(scope) != "write":
                    asked[scope] = level
    granted = workflow["jobs"]["release"]["permissions"]
    assert {scope for scope, level in asked.items() if level == "write"} == {
        scope for scope, level in granted.items() if level == "write"
    }


def _run_manifest_step(tmp_path, job, env):
    step = next(
        step
        for step in release_workflow()["jobs"][job]["steps"]
        if "imagetools create" in step.get("run", "")
    )
    # WHY: records the tags each imagetools call would push instead of writing to GHCR.
    docker = tmp_path / "docker"
    docker.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$DOCKER_CALLS"\n')
    docker.chmod(0o755)
    calls = tmp_path / "calls"
    digests = tmp_path / "digests"
    script = step["run"].replace("/tmp/digests", str(digests))
    subprocess.run(
        ["bash", "-e", "-c", script],
        cwd=digests,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "DOCKER_CALLS": str(calls),
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_SHA": HEAD,
            "VERSION": "1.0.1.dev20261011",
            "PRERELEASE": "true",
            "CHANNEL": "nightly",
            "TAG": "nightly-20261011",
            **env,
        },
        check=True,
    )
    return calls.read_text().splitlines()


def test_the_app_manifest_tags_nightly_and_the_day_and_never_latest(tmp_path):
    (tmp_path / "digests").mkdir()
    (tmp_path / "digests" / ("1" * 64)).touch()
    lines = _run_manifest_step(
        tmp_path, "docker-manifest", {"IMAGE": "ghcr.io/example/app", "APP_ONLY": "false"}
    )
    assert len(lines) == 1
    assert "-t ghcr.io/example/app:nightly-20261011 " in lines[0]
    assert "-t ghcr.io/example/app:nightly " in lines[0]
    assert ":latest" not in lines[0]
    assert "1.0.1.dev20261011" not in lines[0]


@pytest.mark.parametrize("rebuilt", ["true", "false"])
def test_the_inference_manifests_tag_nightly_and_the_day_and_never_latest(tmp_path, rebuilt):
    digests = tmp_path / "digests"
    for folder, digest in [("inference-digests-cpu-0", "2"), ("inference-digests-cuda-2", "3")]:
        (digests / folder).mkdir(parents=True)
        (digests / folder / (digest * 64)).touch()
    image = "ghcr.io/example/app/inference"
    lines = _run_manifest_step(
        tmp_path,
        "inference-manifest",
        {"IMAGE": image, "INFERENCE_ONLY": "false", "REBUILT": rebuilt},
    )
    text = "\n".join(lines)
    assert len(lines) == 2  # cpu, cuda
    assert f"{image}:nightly-20261011 " in text
    assert f"{image}:nightly-20261011-cuda" in text
    assert ":latest" not in text
    if rebuilt == "true":
        assert f"-t {image}:nightly " in text
        assert f"-t {image}:nightly-cuda " in text
    else:
        # The previous nightly's inference images get today's date, unchanged.
        assert lines == [
            f"buildx imagetools create -t {image}:nightly-20261011 {image}:nightly",
            f"buildx imagetools create -t {image}:nightly-20261011-cuda {image}:nightly-cuda",
        ]
