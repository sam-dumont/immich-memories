"""Runtime scratch stays on the configured volume, including in child processes."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


def test_python_and_child_processes_use_configured_storage_and_restore_defaults(tmp_path):
    from immich_memories.security import runtime_scratch

    # Prime Python's cached default: changing TMPDIR alone would leave this behind.
    previous = tempfile.gettempdir()
    previous_env = {key: os.environ.get(key) for key in ("TMPDIR", "TEMP", "TMP")}
    mounted = tmp_path / "mounted-cache"
    with runtime_scratch(mounted):
        with tempfile.TemporaryDirectory() as directory:
            assert Path(directory).is_relative_to(mounted)
            assert Path(directory).stat().st_mode & 0o777 == 0o700
        child = subprocess.check_output(
            [sys.executable, "-c", "import tempfile; print(tempfile.gettempdir())"], text=True
        ).strip()
        assert Path(child).is_relative_to(mounted)
        assert all(os.environ[key] == child for key in previous_env)
        with pytest.raises(RuntimeError, match="interrupted"), runtime_scratch(tmp_path / "nested"):
            assert Path(tempfile.gettempdir()).is_relative_to(tmp_path / "nested")
            raise RuntimeError("interrupted")
        assert tempfile.gettempdir() == child
    assert tempfile.gettempdir() == previous
    assert {key: os.environ.get(key) for key in previous_env} == previous_env


@pytest.mark.parametrize("problem", ["file", "symlink", "public-directory"])
def test_unusable_configured_scratch_fails_without_falling_back_or_exposing_paths(
    tmp_path, problem
):
    from immich_memories.security import runtime_scratch

    mounted = tmp_path / "private-installation"
    mounted.mkdir()
    scratch = mounted / "scratch"
    if problem == "file":
        scratch.write_text("occupied")
    elif problem == "symlink":
        scratch.symlink_to(tmp_path, target_is_directory=True)
    else:
        scratch.mkdir(mode=0o755)
    previous = tempfile.gettempdir()
    with pytest.raises((OSError, RuntimeError)) as failure, runtime_scratch(mounted):
        pytest.fail("An unusable scratch directory must not fall back to system storage")
    assert "private-installation" not in str(failure.value)
    assert "scratch" in str(failure.value)
    assert tempfile.gettempdir() == previous
