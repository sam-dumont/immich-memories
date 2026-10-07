"""Release publication requires deliberate dispatch and a passing image smoke test."""

import json
import os
import shutil
import subprocess
from graphlib import TopologicalSorter
from pathlib import Path

import pytest
import yaml


def release_workflow():
    workflow = yaml.safe_load(Path(".github/workflows/release.yml").read_text())
    # PyYAML reads the GitHub Actions `on` key as a YAML 1.1 boolean.
    workflow["on"] = workflow.pop(True)
    return workflow


@pytest.mark.parametrize(
    ("job", "variant"),
    [("docker-manifest", "app"), ("inference-manifest", "cpu"), ("inference-manifest", "cuda")],
)
@pytest.mark.parametrize(
    "digest", ["sha256:" + "a" * 64, "", "sha256:bad", "sha256:" + "a" * 64 + "\nother=value"]
)
def test_manifest_attestation_uses_only_a_complete_pushed_digest(tmp_path, job, variant, digest):
    steps = release_workflow()["jobs"][job]["steps"]
    step = next(step for step in steps if step.get("id") == f"{variant}-manifest")
    (tmp_path / f"{variant}-manifest.json").write_text(
        json.dumps({"containerimage.descriptor": {"digest": digest}})
    )
    output = tmp_path / "output"
    result = subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        env={**os.environ, "RUNNER_TEMP": str(tmp_path), "GITHUB_OUTPUT": str(output)},
        capture_output=True,
        timeout=10,
    )
    if digest == "sha256:" + "a" * 64:
        assert result.returncode == 0
        assert output.read_text() == f"digest={digest}\n"
    else:
        assert result.returncode != 0
        assert not output.exists()


def test_a_merge_to_main_does_not_publish_a_release():
    assert set(release_workflow()["on"]) == {"workflow_dispatch"}


def test_release_publication_waits_for_the_image_smoke_test():
    jobs = release_workflow()["jobs"]
    dependencies = {name: set(job.get("needs", [])) for name, job in jobs.items()}
    tuple(TopologicalSorter(dependencies).static_order())

    def ancestors(name):
        return dependencies[name] | {
            ancestor for parent in dependencies[name] for ancestor in ancestors(parent)
        }

    for publication in ("release", "pypi-publish", "docker-manifest", "deploy-docs"):
        assert "docker-smoke" in ancestors(publication), publication


def test_nothing_irreversible_happens_until_nothing_can_fail():
    # The tag, the GitHub Release and PyPI cannot be taken back, so every job that
    # can still fail runs first. rc.6's wheel went out while its CUDA image failed.
    jobs = release_workflow()["jobs"]
    dependencies = {name: set(job.get("needs", [])) for name, job in jobs.items()}

    def ancestors(name):
        return dependencies[name] | {
            ancestor for parent in dependencies[name] for ancestor in ancestors(parent)
        }

    fallible = {
        "ci",
        "package",
        "docker-build",
        "docker-smoke",
        "inference-build",
        "docker-manifest",
        "inference-manifest",
        "deployment-bundle",
    }
    assert fallible <= ancestors("release")
    for later in ("pypi-publish-music", "pypi-publish", "deploy-docs"):
        assert "release" in ancestors(later), later
    for irreversible in ("release", "pypi-publish-music", "pypi-publish"):
        for job in ("ci", "package", "docker-build", "docker-smoke", "inference-build"):
            assert irreversible not in ancestors(job), (irreversible, job)
    # A version tag in the registry only moves once every phase-1 job has succeeded.
    for manifest in ("docker-manifest", "inference-manifest"):
        assert {"package", "docker-smoke", "inference-build", "ci"} <= ancestors(manifest)


def test_dry_run_uses_boolean_guards_for_publication():
    workflow = release_workflow()
    for job in workflow["jobs"].values():
        for item in (job, *job.get("steps", [])):
            condition = item.get("if", "")
            assert "inputs.dry_run != 'true'" not in condition
            assert "inputs.dry_run == 'true'" not in condition
    release_steps = workflow["jobs"]["release"]["steps"]
    assert "!inputs.dry_run" in workflow["jobs"]["release"]["if"]
    assert any("git push" in step.get("run", "") for step in release_steps)
    for name in ("pypi-publish", "pypi-publish-music", "docker-build", "deploy-docs"):
        assert "!inputs.dry_run" in workflow["jobs"][name]["if"]


def test_package_build_finishes_before_the_release_tag_is_pushed():
    jobs = release_workflow()["jobs"]
    assert any(step.get("run") == "uv build" for step in jobs["package"]["steps"])
    assert "package" in jobs["release"]["needs"]
    assert not any(step.get("run") == "uv build" for step in jobs["release"]["steps"])


def test_the_first_registry_push_keeps_the_release_environment_approval():
    jobs = release_workflow()["jobs"]

    def guarded(name):
        job = jobs[name]
        return "production-major" in str(job.get("environment", "")) or any(
            guarded(parent) for parent in job.get("needs", [])
        )

    assert guarded("docker-build")


def test_secret_scan_checks_every_unreleased_commit_independent_of_event(tmp_path):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, env=env, text=True).strip()

    git("init", "-q")
    git("config", "user.name", "Release test")
    git("config", "user.email", "release@example.test")
    git("commit", "--allow-empty", "-qm", "fix: released")
    git("tag", "v1.2.3")
    git("commit", "--allow-empty", "-qm", "fix: first change")
    first = git("rev-parse", "HEAD")
    git("commit", "--allow-empty", "-qm", "fix: second change")
    second = git("rev-parse", "HEAD")
    scanner = tmp_path / "gitleaks"
    # WHY: capture the external scanner's range without requiring its binary in unit CI.
    scanner.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > scan-args.txt\n')
    scanner.chmod(0o755)
    for event in ("pull_request", "push", "workflow_dispatch"):
        subprocess.run(
            ["make", "-f", str(Path("Makefile").resolve()), "secret-scan"],
            cwd=tmp_path,
            env={**env, "PATH": f"{tmp_path}:{env['PATH']}", "GITHUB_EVENT_NAME": event},
            check=True,
            capture_output=True,
            text=True,
        )
        args = (tmp_path / "scan-args.txt").read_text().splitlines()
        assert "--redact" in args
        scan_range = next(
            arg.removeprefix("--log-opts=") for arg in args if arg.startswith("--log-opts=")
        )
        assert set(git("rev-list", scan_range).splitlines()) == {first, second}


@pytest.mark.parametrize(
    "message",
    [
        "fix(api)!: remove the obsolete endpoint",
        "docs!: remove the legacy installation path",
        "feat: replace the configuration\n\nBREAKING CHANGE: the old key is no longer accepted",
        "fix!: incompatible change\n\n" + "Detailed integration history.\n" * 2000,
    ],
    ids=["fix-marker", "docs-marker", "body-footer", "long-squash-body"],
)
def test_breaking_squash_messages_produce_a_major_release(tmp_path, message):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    for args in (
        ("init", "-q"),
        ("config", "user.name", "Release test"),
        ("config", "user.email", "release@example.test"),
        ("commit", "--allow-empty", "-qm", "fix: released"),
        ("tag", "v1.2.3"),
        ("commit", "--allow-empty", "-qm", message),
    ):
        subprocess.run(["git", *args], cwd=tmp_path, env=env, check=True, capture_output=True)
    # WHY: v1.2.3 stands for a published release here; the fake gh answers the
    # release-existence question the analyze step asks GitHub in production.
    (tmp_path / "gh").write_text("#!/bin/sh\nexit 0\n")
    (tmp_path / "gh").chmod(0o755)
    env = {**env, "PATH": f"{tmp_path}:{env['PATH']}"}
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy(
        Path(__file__).parents[1] / "scripts" / "release_analyze.py",
        scripts / "release_analyze.py",
    )
    analyze = next(
        step
        for step in release_workflow()["jobs"]["analyze"]["steps"]
        if step.get("id") == "analyze"
    )
    output = tmp_path / "outputs"
    subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", analyze["run"]],
        cwd=tmp_path,
        env={
            **env,
            "GITHUB_OUTPUT": str(output),
            "FORCE_VERSION": "auto",
            "INFERENCE_ONLY": "false",
        },
        check=True,
        capture_output=True,
        text=True,
    )
    assert "next_version=2.0.0" in output.read_text().splitlines()


def test_an_interrupted_release_is_resumed_with_the_same_version(tmp_path):
    """Tag pushed, GitHub Release never created: the next run republishes it (#1010)."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    for args in (
        ("init", "-q"),
        ("config", "user.name", "Release test"),
        ("config", "user.email", "release@example.test"),
        ("commit", "--allow-empty", "-qm", "fix: released"),
        ("tag", "v1.2.3"),
        ("commit", "--allow-empty", "-qm", "fix: released"),
        ("tag", "-a", "v1.2.4", "-m", "Release v1.2.4"),
    ):
        subprocess.run(["git", *args], cwd=tmp_path, env=env, check=True, capture_output=True)
    # WHY: v1.2.4 exists as a tag but its publication failed before the GitHub
    # Release was created, so the fake gh reports no release for it.
    (tmp_path / "gh").write_text("#!/bin/sh\nexit 1\n")
    (tmp_path / "gh").chmod(0o755)
    env = {**env, "PATH": f"{tmp_path}:{env['PATH']}"}
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy(
        Path(__file__).parents[1] / "scripts" / "release_analyze.py",
        scripts / "release_analyze.py",
    )
    analyze = next(
        step
        for step in release_workflow()["jobs"]["analyze"]["steps"]
        if step.get("id") == "analyze"
    )
    output = tmp_path / "outputs"
    subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", analyze["run"]],
        cwd=tmp_path,
        env={
            **env,
            "GITHUB_OUTPUT": str(output),
            "FORCE_VERSION": "auto",
            "INFERENCE_ONLY": "false",
        },
        check=True,
        capture_output=True,
        text=True,
    )
    lines = output.read_text().splitlines()
    assert "should_release=true" in lines
    assert "next_version=1.2.4" in lines, "the stranded version, not an advance past it"


def test_the_first_release_candidate_of_a_major_is_rc_1(tmp_path):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    for args in (
        ("init", "-q"),
        ("config", "user.name", "Release test"),
        ("config", "user.email", "release@example.test"),
        ("commit", "--allow-empty", "-qm", "fix: released"),
        ("tag", "v0.103.0"),
        ("commit", "--allow-empty", "-qm", "fix: after the last final"),
    ):
        subprocess.run(["git", *args], cwd=tmp_path, env=env, check=True, capture_output=True)
    # WHY: v0.103.0 stands for a published release; the fake gh answers the
    # release-existence question the analyze step asks GitHub in production.
    (tmp_path / "gh").write_text("#!/bin/sh\nexit 0\n")
    (tmp_path / "gh").chmod(0o755)
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy(
        Path(__file__).parents[1] / "scripts" / "release_analyze.py",
        scripts / "release_analyze.py",
    )
    analyze = next(
        step
        for step in release_workflow()["jobs"]["analyze"]["steps"]
        if step.get("id") == "analyze"
    )
    output = tmp_path / "outputs"
    subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", analyze["run"]],
        cwd=tmp_path,
        env={
            **env,
            "PATH": f"{tmp_path}:{env['PATH']}",
            "GITHUB_OUTPUT": str(output),
            "FORCE_VERSION": "major",
            "CHANNEL": "rc",
            "INFERENCE_ONLY": "false",
        },
        check=True,
        capture_output=True,
        text=True,
    )
    lines = output.read_text().splitlines()
    assert "next_version=1.0.0-rc.1" in lines
    assert "prerelease=true" in lines
    assert "previous_tag=v0.103.0" in lines


@pytest.mark.parametrize(
    ("prerelease", "app_only", "tag", "moves_latest"),
    [
        ("true", "false", "1.0.0-rc.1", False),
        ("false", "false", "1.0.0-rc.1", True),
        ("false", "true", "sha-aaaaaaaaaaaa", False),
    ],
)
def test_image_tags_match_dispatch_mode(tmp_path, prerelease, app_only, tag, moves_latest):
    step = next(
        step
        for step in release_workflow()["jobs"]["docker-manifest"]["steps"]
        if "imagetools" in step.get("run", "")
    )
    digests = tmp_path / "digests"
    digests.mkdir()
    (digests / "abc123").touch()
    # WHY: records the tags the step would push instead of writing to the registry.
    (tmp_path / "docker").write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$ARGS_FILE"\n')
    (tmp_path / "docker").chmod(0o755)
    args_file = tmp_path / "args.txt"
    subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        cwd=digests,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "ARGS_FILE": str(args_file),
            "IMAGE": "ghcr.io/example/app",
            "VERSION": "1.0.0-rc.1",
            "PRERELEASE": prerelease,
            "APP_ONLY": app_only,
            "GITHUB_SHA": "a" * 40,
        },
        check=True,
    )
    args = args_file.read_text().splitlines()
    assert f"ghcr.io/example/app:{tag}" in args
    assert ("ghcr.io/example/app:latest" in args) is moves_latest


def test_a_release_candidate_can_publish_docs():
    condition = release_workflow()["jobs"]["deploy-docs"]["if"]
    assert "prerelease" not in condition


@pytest.mark.parametrize(("inference_only", "succeeds"), [("false", True), ("true", False)])
def test_app_only_workflow_runs_image_gates_without_release_publication(
    tmp_path, inference_only, succeeds
):
    workflow = release_workflow()
    assert workflow["on"]["workflow_dispatch"]["inputs"]["app_only"]["type"] == "boolean"
    jobs = workflow["jobs"]
    for name in ("ci", "docker-build"):
        assert "inputs.app_only" in jobs[name]["if"]
    for name in (
        "package",
        "release",
        "pypi-publish",
        "pypi-publish-music",
        "deploy-docs",
        "deployment-bundle",
    ):
        assert "needs.analyze.outputs.should_release == 'true'" in jobs[name]["if"]
        assert "inputs.app_only" not in jobs[name]["if"]
    manifest = next(
        step for step in jobs["docker-manifest"]["steps"] if "imagetools" in step.get("run", "")
    )
    assert manifest["env"]["APP_ONLY"] == "${{ inputs.app_only }}"
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy(Path("scripts/release_analyze.py"), scripts / "release_analyze.py")
    step = next(step for step in jobs["analyze"]["steps"] if step.get("id") == "analyze")
    output = tmp_path / "outputs"
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", step["run"]],
        cwd=tmp_path,
        env={
            **os.environ,
            "APP_ONLY": "true",
            "INFERENCE_ONLY": inference_only,
            "GITHUB_SHA": "a" * 40,
            "GITHUB_OUTPUT": str(output),
        },
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) is succeeds, result.stderr
    if succeeds:
        assert output.read_text().splitlines() == [
            "should_release=false",
            "next_version=0+g" + "a" * 40,
        ]
    else:
        assert not output.exists() or output.read_text() == ""


def test_docs_publication_waits_for_matching_deployment_assets():
    jobs = release_workflow()["jobs"]
    assert "deployment-bundle" in jobs["deploy-docs"]["needs"]
    assert "deployment-bundle" in jobs["release"]["needs"]


def test_published_installation_inputs_have_matching_checksums_and_image_identity(tmp_path):
    import hashlib

    step = next(
        step
        for step in release_workflow()["jobs"]["deployment-bundle"]["steps"]
        if step.get("name") == "Package deployment files"
    )
    binaries = tmp_path / "bin"
    binaries.mkdir()
    # The package job's wheel arrives as a workflow artifact, not from a release.
    wheels = tmp_path / "dist-release"
    wheels.mkdir()
    (wheels / "immich_memories-0.0.0.dev12345-py3-none-any.whl").write_bytes(b"fixture wheel")
    manifest = {
        "digest": "sha256:" + "a" * 64,
        "manifests": [{"platform": {"os": "linux", "architecture": "amd64"}}],
    }
    docker = binaries / "docker"
    docker.write_text(
        f'#!/bin/sh\nprintf \'%s\\n\' "$4" >> "$RUNNER_TEMP/inspected-images"\n'
        f"printf '%s' '{json.dumps(manifest)}'\n"
    )
    docker.chmod(0o700)
    if shutil.which("sha256sum") is None:
        checksum = binaries / "sha256sum"
        checksum.write_text('#!/bin/sh\nexec shasum -a 256 "$@"\n')
        checksum.chmod(0o700)
    subprocess.run(
        ["bash", "-eu", "-o", "pipefail", "-c", step["run"]],
        env={
            **os.environ,
            "PATH": f"{binaries}:{os.environ['PATH']}",
            "RUNNER_TEMP": str(tmp_path),
            "VERSION": "0.0.0-dev.12345",
            "GITHUB_SHA": "b" * 40,
        },
        check=True,
        capture_output=True,
        text=True,
    )
    assert (tmp_path / "inspected-images").read_text().splitlines() == [
        "ghcr.io/sam-dumont/immich-memories:0.0.0-dev.12345",
        "ghcr.io/sam-dumont/immich-memories/inference:0.0.0-dev.12345",
        "ghcr.io/sam-dumont/immich-memories/inference:0.0.0-dev.12345-cuda",
    ]
    assets = tmp_path / "immich-memories-compose-0.0.0-dev.12345"
    identity = json.loads((assets / "installation.json").read_text())
    assert identity["version"] == "0.0.0-dev.12345"
    assert identity["source_commit"] == "b" * 40
    assert set(identity["images"]) == {"app", "inference", "cuda"}
    assert identity["images"]["app"] == manifest
    checksums = dict(
        line.split(maxsplit=1)[::-1] for line in (assets / "SHA256SUMS").read_text().splitlines()
    )
    bundle = "immich-memories-deploy-0.0.0-dev.12345.tar.gz"
    assert {
        bundle,
        "example.env",
        "docker-compose.yml",
        "installation.json",
        "immich_memories-0.0.0.dev12345-py3-none-any.whl",
    } <= checksums.keys()
    for name, digest in checksums.items():
        assert digest == hashlib.sha256((assets / name).read_bytes()).hexdigest()


def test_versioned_native_docs_wait_for_pypi_except_rehearsals():
    jobs = release_workflow()["jobs"]
    docs = jobs["deploy-docs"]
    assert "pypi-publish" in docs["needs"]
    assert "needs.pypi-publish.result == 'success'" in docs["if"]
    assert "inputs.channel == 'dev'" in docs["if"]
    assert "!cancelled()" in docs["if"]
    for job in ("pypi-publish", "pypi-publish-music"):
        assert "inputs.channel != 'dev'" in jobs[job]["if"]
