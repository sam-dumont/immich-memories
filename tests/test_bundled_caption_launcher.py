"""Run the shipped launcher without loading a model or requiring a GPU."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

LAUNCHER = Path(__file__).resolve().parents[1] / "docker/captioner-bundled.sh"


def launch_captioner(cache_ram: str | None = None, *arguments: str) -> dict:
    env = {key: value for key, value in os.environ.items() if key != "LLAMA_ARG_CACHE_RAM"}
    if cache_ram is not None:
        env["LLAMA_ARG_CACHE_RAM"] = cache_ram
    env["LAUNCHER_TEST_PYTHON"] = sys.executable
    # WHY: intercept only the final executable boundary; the real launcher still
    # expands its defaults, environment and arguments in a shell.
    shell = """
exec() {
    "$LAUNCHER_TEST_PYTHON" -c '
import json, os, sys
print(json.dumps({"cache_ram": os.environ.get("LLAMA_ARG_CACHE_RAM"), "argv": sys.argv[1:]}))
' "$@"
}
launcher=$1
shift
. "$launcher"
"""
    result = subprocess.run(
        ["bash", "-c", shell, "caption-test", str(LAUNCHER), *arguments],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_bundled_captioner_limits_host_prompt_cache_by_default():
    launched = launch_captioner()

    assert launched["argv"][0] == "/opt/llama/llama-server"
    assert launched["cache_ram"] == "128"


@pytest.mark.parametrize("cache_ram", ["0", "256", "-1"])
def test_bundled_captioner_preserves_explicit_upstream_cache_setting(cache_ram):
    assert launch_captioner(cache_ram)["cache_ram"] == cache_ram


def test_bundled_captioner_keeps_command_line_overrides():
    launched = launch_captioner("256", "--cache-ram", "64")

    assert launched["cache_ram"] == "256"
    assert launched["argv"][-2:] == ["--cache-ram", "64"]
