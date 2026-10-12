"""Cross-surface contract for the application build version."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

import immich_memories
from immich_memories._version import __version__ as generated_version

REPO_ROOT = Path(__file__).resolve().parents[1]


def _parse_make_target_prerequisites(output: str, target: str) -> set[str]:
    """Extract real prerequisites from Make's database output."""
    prefix = f"{target}:"
    prerequisites: set[str] = set()
    for line in output.splitlines():
        if not line.startswith(prefix):
            continue
        declaration = line.removeprefix(prefix).strip()
        # GNU Make emits target-specific variable assignments using the same
        # ``target:`` prefix as dependency declarations.
        if " = " in declaration:
            continue
        prerequisites.update(
            prerequisite for prerequisite in declaration.split() if prerequisite != "|"
        )
    return prerequisites


def _make_target_prerequisites(target: str) -> set[str]:
    result = subprocess.run(
        ["make", "--no-print-directory", "-qp"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode in {0, 1}, result.stderr
    return _parse_make_target_prerequisites(result.stdout, target)


def _make_dry_run(target: str) -> str:
    result = subprocess.run(
        ["make", "--no-print-directory", "-n", target],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _ci_success_result(**results: str) -> subprocess.CompletedProcess[str]:
    """Run the checked-in summary gate with these job results; unnamed jobs succeeded."""
    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text())
    gate = workflow["jobs"]["ci-success"]
    step = gate["steps"][0]
    assert step["env"]["RESULTS"] == "${{ toJSON(needs) }}"
    needs = {
        job: {"result": results.get(job.replace("-", "_"), "success")} for job in gate["needs"]
    }
    return subprocess.run(
        ["bash", "-o", "pipefail", "-c", step["run"]],
        cwd=REPO_ROOT,
        env={**os.environ, "RESULTS": json.dumps(needs)},
        check=False,
        capture_output=True,
        text=True,
    )


def test_package_exports_generated_version() -> None:
    """The public package version must be the version Hatch VCS generated."""
    assert immich_memories.__version__ == generated_version


def test_hatch_vcs_is_the_only_configured_version_source() -> None:
    """Packaging and release tooling must not maintain a second static version."""
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())

    assert pyproject["tool"]["hatch"]["version"]["source"] == "vcs"
    semantic_release = pyproject["tool"]["semantic_release"]
    assert "version" not in semantic_release
    assert "version_toml" not in semantic_release


def test_launch_check_composes_every_release_gate() -> None:
    """One local target must exercise the same artifacts required for launch."""
    assert _make_target_prerequisites("launch-check") == {
        "check",
        "build",
        "build-check",
        "docs-check",
        "e2e",
    }


def test_make_prerequisite_parser_ignores_target_specific_variables() -> None:
    """GNU Make may print target-specific assignments before prerequisites in CI."""
    output = """launch-check: ENSURE_DEV_COMMAND = echo preinstalled
launch-check: check build build-check docs-check e2e
"""

    assert _parse_make_target_prerequisites(output, "launch-check") == {
        "check",
        "build",
        "build-check",
        "docs-check",
        "e2e",
    }


@pytest.mark.parametrize("target", ["launch-check", "launch-check-ci"])
def test_launch_check_consumes_the_preinstalled_ci_environment(target: str) -> None:
    """The launch job must not replace dev-test with every heavyweight extra."""
    commands = _make_dry_run(target)

    assert "uv sync --all-extras" not in commands
    assert "Using preinstalled launch-check dependencies" in commands


def _job_steps(job: dict) -> list[dict]:
    """A CI job's steps, with the shared launch-suite setup's own steps in its place."""
    steps: list[dict] = []
    for step in job["steps"]:
        if step.get("uses") == "./.github/actions/setup-launch-suite":
            action = REPO_ROOT / ".github" / "actions" / "setup-launch-suite" / "action.yml"
            steps.extend(yaml.safe_load(action.read_text())["runs"]["steps"])
        else:
            steps.append(step)
    return steps


def test_ci_runs_the_hermetic_launch_check_with_runtime_dependencies() -> None:
    """Pull requests must run the browser/FFmpeg launch gate without credentials."""
    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text())
    launch_job = workflow["jobs"]["launch-check"]
    steps = _job_steps(launch_job)
    commands = "\n".join(str(step.get("run", "")) for step in steps)
    setup = next(s for s in launch_job["steps"] if "setup-launch-suite" in str(s.get("uses")))

    # Each leg runs about half the files (E2E_SHARD), well inside 30 minutes.
    assert launch_job["timeout-minutes"] == 30
    assert '["sqlite","postgresql"]' in launch_job["strategy"]["matrix"]["database"]
    assert any(step.get("uses") == "./.github/actions/install-ffmpeg" for step in steps)
    assert "playwright install --with-deps chromium" in commands
    assert setup["with"]["browser"] == "true"
    # Exact target: "make launch-check" is a substring of "make launch-check-ci",
    # so a loose check would pass whichever one CI pointed at.
    shard = r"E2E_SHARD=\$\{\{ matrix\.shard \}\}/\d+"
    assert re.search(rf"^\s*make launch-check-ci {shard}\s*$", commands, re.M)
    assert re.search(rf"^\s*make launch-check-ci-postgres {shard}\s*$", commands, re.M)
    assert all("IMMICH_API_KEY" not in str(step) for step in steps)

    lfs_pull_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("uses") == "./.github/actions/pull-lfs"
    )
    lfs_action = (REPO_ROOT / ".github" / "actions" / "pull-lfs" / "action.yml").read_text()
    assert "git lfs pull" in lfs_action
    launch_index = next(
        index
        for index, step in enumerate(steps)
        if "make launch-check-ci" in str(step.get("run", ""))
    )
    assert lfs_pull_index < launch_index

    upload = next(
        step for step in steps if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    )
    assert upload["if"] == "failure()"
    artifact_paths = str(upload["with"]["path"])
    for expected in ("tests/e2e-junit.xml", "server.log", "output-probe.json"):
        assert expected in artifact_paths
    assert "launch-smoke*/output/**" in artifact_paths


def test_ci_runs_the_feature_suite_in_shards_with_the_music_extra() -> None:
    """Each feature job installs the bundled tracks and runs its slice of the files."""
    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text())
    job = workflow["jobs"]["features"]
    commands = "\n".join(str(step.get("run", "")) for step in _job_steps(job))
    setup = next(s for s in job["steps"] if s.get("uses") == "./.github/actions/setup-launch-suite")

    assert setup["with"]["install"] == "dev-test-features"
    assert re.search(
        r"^\s*make test-features FEATURE_SHARD=\$\{\{ matrix\.shard \}\}/\d+\s*$", commands, re.M
    )


@pytest.mark.parametrize(
    ("workflow", "job", "key"),
    [
        ("ci.yml", "launch-check", "shard"),
        ("ci.yml", "features", "shard"),
        ("ci.yml", "test", "shard"),  # only the coverage cell's shards upload
        ("ci.yml", "integration-coverage", "suite"),
        ("immich-gate.yml", "features", "shard"),
    ],
)
def test_each_shard_uploads_its_artifacts_under_its_own_name(workflow: str, job: str, key: str):
    """Two legs uploading one artifact name collide, and the second upload fails."""
    jobs = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / workflow).read_text())["jobs"]
    uploads = [
        step
        for step in jobs[job]["steps"]
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    ]

    assert uploads
    assert all(f"${{{{ matrix.{key} }}}}" in step["with"]["name"] for step in uploads)


@pytest.mark.parametrize("workflow", ["ci.yml", "immich-gate.yml"])
def test_an_upload_of_a_hidden_path_asks_for_hidden_files(workflow: str) -> None:
    """upload-artifact skips dot-paths unless told: the Immich logs never reached a failed run."""
    jobs = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / workflow).read_text())["jobs"]
    for job in jobs.values():
        for step in job.get("steps", []):
            if not str(step.get("uses", "")).startswith("actions/upload-artifact@"):
                continue
            paths = str(step["with"]["path"]).split()
            if any(part.startswith(".") for path in paths for part in Path(path).parts):
                assert step["with"].get("include-hidden-files") is True, step


def test_duplication_gate_pins_a_supported_jscpd_cli() -> None:
    """The duplication gate must not install an arbitrary future CLI release."""
    commands = _make_dry_run("duplication")

    assert "jscpd@5.0.14" in commands
    assert "--gitignore" not in commands


def test_cognitive_complexity_gate_pins_its_analyzer_and_judges_by_the_watermark() -> None:
    """The watermark is read against the analyzer version that measured it (#1550).

    complexipy's own line-numbered snapshot is ignored; its fresh results go to the
    watermark script, which fails when there are none, so a crashed analyzer is no pass.
    """
    commands = _make_dry_run("cognitive-complexity")
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())

    assert "complexipy==5.2.0" in commands
    assert "--snapshot-ignore" in commands
    assert "--output-json" in commands
    assert "scripts/complexity_watermark.py complexipy_results_*.json" in commands
    assert "exit $STATUS" in commands
    assert pyproject["tool"]["complexipy"]["exclude"] == ["_version.py"]


def test_dependency_audit_uses_the_frozen_ci_resolution() -> None:
    """Security results must not depend on the caller's ambient virtualenv."""
    commands = _make_dry_run("pip-audit")

    assert (
        "uv export --frozen --extra dev --extra all --no-emit-project --no-emit-package immich-memories-music --no-hashes"
        in commands
    )
    assert "uv pip freeze" not in commands
    # The export is pinned: re-resolving it from PyPI's index only adds a way to fail.
    assert "--no-deps --disable-pip" in commands


@pytest.mark.parametrize(
    ("results", "expected_returncode"),
    [
        ({}, 0),
        # The change scope left the launch check out; skipped is how GitHub reports that.
        ({"launch_check": "skipped"}, 0),
        # A job past its timeout-minutes ends cancelled: never a pass.
        ({"launch_check": "cancelled"}, 1),
        ({"launch_check": "failure"}, 1),
        ({"setup": "failure", "launch_check": "skipped"}, 1),
        # Without a scope every job skips; that must not read as all green.
        ({"changes": "failure", "test": "skipped", "launch_check": "skipped"}, 1),
    ],
)
def test_ci_summary_gate_passes_only_success_or_a_scoped_skip(
    results: dict[str, str], expected_returncode: int
) -> None:
    """CI Success is the required check: it fails on any job that failed, timed out or never had a scope."""
    result = _ci_success_result(**results)

    assert result.returncode == expected_returncode, result.stdout + result.stderr


def test_ci_launch_gate_does_not_rerun_what_has_its_own_job() -> None:
    """The launch job must contribute the e2e gate, not repeat the whole pipeline.

    `make launch-check` chains check + build + build-check + docs-check + e2e,
    and CI already runs every one of those as a dedicated parallel job — lint,
    typecheck, file-length, complexity, a six-cell test matrix, Build Package
    (which runs build and build-check) and docs. Re-running them made this the
    longest job in CI, and under runner starvation it was killed at ~80% of the
    test suite, before ever reaching the browser render it exists for.
    """
    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text())
    target = next(
        match.group(1)
        for step in workflow["jobs"]["launch-check"]["steps"]
        if (match := re.search(r"make (launch-check\S*)", str(step.get("run", ""))))
    )

    prerequisites = _make_target_prerequisites(target)

    assert "e2e" in prerequisites, "the launch gate must still run the hermetic render"
    assert not prerequisites & {"check", "test", "docs-check", "build"}, (
        f"{target} repeats work that already has its own CI job: {sorted(prerequisites)}"
    )
