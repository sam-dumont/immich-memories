"""Dispatched text stays data before it reaches JSON validation or GPU checkout."""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def step_script(workflow, job, name):
    steps = yaml.safe_load((WORKFLOWS / workflow).read_text())["jobs"][job]["steps"]
    return next(step["run"] for step in steps if step.get("name") == name)


def test_benchmark_results_cannot_end_the_shell_data_boundary(tmp_path):
    sentinel = tmp_path / "executed"
    payload = f"RESULTS_EOF\ntouch {sentinel}\n#"
    script = step_script("benchmark.yml", "ingest", "Validate and project submitted results")
    # Reproduce GitHub's script interpolation if it is still present in this workflow.
    script = script.replace("${{ github.event.inputs.results }}", payload)
    script = script.replace("${{ github.event.inputs.suite }}", "all")
    script = script.replace("${{ github.event.inputs.runner }}", "local")
    script = script.replace("${{ github.event.inputs.sha || 'not specified' }}", "not specified")
    result = subprocess.run(
        ["bash", "-e", "-c", script],
        cwd=WORKFLOWS.parents[1],
        env={
            **os.environ,
            "RESULTS_JSON": payload,
            "RUNNER_NAME": "local",
            "SUITE": "all",
            "SHA": "",
        },
        capture_output=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert not sentinel.exists()


@pytest.mark.parametrize(
    "overrides",
    [
        {"REQUEST_SHA": "a" * 40 + "\nsuite=cli"},
        {"PUBLIC_REPO": "outsider/repo"},
        {"BRANCH": "../bad"},
    ],
)
def test_invalid_gpu_dispatch_is_refused_before_any_outputs(tmp_path, overrides):
    output = tmp_path / "output"
    script = step_script("integration.yml", "integration", "Resolve params")
    env = {
        **os.environ,
        "REQUEST_SHA": "a" * 40,
        "BRANCH": "main",
        "SUITE": "all",
        "PUBLIC_REPO": "sam-dumont/immich-video-memory-generator",
        "GITHUB_OUTPUT": str(output),
        **overrides,
    }
    result = subprocess.run(["bash", "-e", "-c", script], env=env, capture_output=True, timeout=10)
    assert result.returncode != 0
    assert not output.exists() or not output.read_text()


def test_valid_gpu_dispatch_outputs_the_exact_requested_commit(tmp_path):
    output = tmp_path / "output"
    env = {
        **os.environ,
        "REQUEST_SHA": "b" * 40,
        "BRANCH": "fix/a-branch",
        "SUITE": "titles",
        "PUBLIC_REPO": "sam-dumont/immich-video-memory-generator",
        "GITHUB_OUTPUT": str(output),
    }
    script = step_script("integration.yml", "integration", "Resolve params")
    subprocess.run(
        ["bash", "-e", "-c", script], env=env, check=True, capture_output=True, timeout=10
    )
    assert output.read_text().splitlines() == [
        "sha=" + "b" * 40,
        "branch=fix/a-branch",
        "public_repo=sam-dumont/immich-video-memory-generator",
        "suite=titles",
    ]
