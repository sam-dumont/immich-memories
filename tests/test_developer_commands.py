"""Developer commands select compatible runtimes and the intended test tiers."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_dev_install_selects_only_cpu_onnx_on_linux(tmp_path):
    commands = subprocess.run(
        ["make", "--no-print-directory", "-n", "dev"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    sync = next(line for line in commands.stdout.splitlines() if line.startswith("uv sync "))
    result = subprocess.run(
        [*shlex.split(sync), "--frozen", "--dry-run", "--offline", "--python-platform", "linux"],
        cwd=ROOT,
        env={**os.environ, "UV_PROJECT_ENVIRONMENT": str(tmp_path / "venv")},
        capture_output=True,
        text=True,
        check=True,
    )
    assert "+ onnxruntime==" in result.stderr
    assert "+ onnxruntime-gpu==" not in result.stderr


def test_fast_does_not_run_external_or_slow_tiers(tmp_path):
    (tmp_path / "test_tiers.py").write_text(
        "import pytest\n\ndef test_unit(): pass\n"
        + "\n".join(
            f"@pytest.mark.{marker}\ndef test_{marker}(): assert False\n"
            for marker in ("slow", "integration", "e2e", "container")
        )
    )
    runner = tmp_path / "uv"
    # WHY: only replace uv's environment selection; execute real pytest with the real Make target.
    runner.write_text(f'#!/bin/sh\nshift 2\nexec {shlex.quote(sys.executable)} -m pytest "$@"\n')
    runner.chmod(0o755)
    result = subprocess.run(
        ["make", "--no-print-directory", "-f", str(ROOT / "Makefile"), "test-fast"],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
            "PYTEST_ADDOPTS": "",
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout
    assert "4 deselected" in result.stdout


@pytest.mark.parametrize("extra", ["editorial", "all", "all-mac"])
def test_cuda_runtime_refuses_cpu_extras(tmp_path, extra):
    result = subprocess.run(
        [
            "uv",
            "sync",
            "--frozen",
            "--dry-run",
            "--offline",
            "--python-platform",
            "linux",
            "--extra",
            "editorial-cuda",
            "--extra",
            extra,
        ],
        cwd=ROOT,
        env={**os.environ, "UV_PROJECT_ENVIRONMENT": str(tmp_path / "venv")},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "conflict" in result.stderr.lower()


def test_cuda_editorial_selects_only_gpu_onnx_on_linux(tmp_path):
    result = subprocess.run(
        [
            "uv",
            "sync",
            "--frozen",
            "--dry-run",
            "--offline",
            "--python-platform",
            "linux",
            "--extra",
            "editorial-cuda",
            "--extra",
            "dev",
        ],
        cwd=ROOT,
        env={**os.environ, "UV_PROJECT_ENVIRONMENT": str(tmp_path / "venv")},
        capture_output=True,
        text=True,
        check=True,
    )
    assert "+ onnxruntime-gpu==" in result.stderr
    assert "+ onnxruntime==" not in result.stderr


@pytest.mark.parametrize("extra", ["none", "editorial", "all", "editorial-cuda"])
def test_image_constraints_export_accepts_selected_extra(tmp_path, extra):
    dockerfile = (ROOT / "docker/Dockerfile").read_text()
    instructions = re.sub(r"\\\s*\n\s*", " ", dockerfile).splitlines()
    command = next(
        line[4:] for line in instructions if line.startswith("RUN ") and "/constraints.txt" in line
    )
    # WHY: skip the package installation write; execute the image's real lock export and selector.
    command = re.sub(r"pip install .*? && ", "", command)
    command = command.replace("/constraints.txt", shlex.quote(str(tmp_path / "constraints.txt")))
    result = subprocess.run(
        ["sh", "-c", command],
        cwd=ROOT,
        env={**os.environ, "INSTALL_EXTRAS": extra},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "constraints.txt").is_file()
