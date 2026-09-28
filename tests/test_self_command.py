"""A run's child command is this install, whatever `immich-memories` PATH finds first."""

from __future__ import annotations

import os
import stat
import subprocess
from datetime import date

from immich_memories import __version__
from immich_memories.automation.candidates import CandidateCategory, MemoryCandidate
from immich_memories.automation.generation_request import GenerationRequest


def _shadowing_install(tmp_path) -> str:
    """A PATH whose `immich-memories` is some other install: it fails loudly if it runs."""
    impostor = tmp_path / "immich-memories"
    impostor.write_text("#!/bin/sh\necho 'the other install ran' >&2\nexit 42\n")
    impostor.chmod(impostor.stat().st_mode | stat.S_IEXEC)
    return f"{tmp_path}{os.pathsep}{os.environ['PATH']}"


def _request() -> GenerationRequest:
    candidate = MemoryCandidate(
        memory_type="monthly_highlights",
        category=CandidateCategory.MONTHLY_REVIEW,
        date_range_start=date(2025, 1, 1),
        date_range_end=date(2025, 1, 31),
        person_names=[],
        memory_key="key:monthly",
        score=0.75,
        reason="test candidate",
        asset_count=100,
    )
    return GenerationRequest.from_candidate(candidate, False)


def test_the_automation_child_is_this_install_even_when_path_names_another(tmp_path):
    argv = _request().to_argv()
    probe = [*argv[: argv.index("generate")], "--version"]

    result = subprocess.run(  # noqa: S603 - argv built by the code under test
        probe,
        env={**os.environ, "PATH": _shadowing_install(tmp_path)},
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert __version__ in result.stdout
