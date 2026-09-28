"""Timing instrumentation must not drag the database layer into what it measures."""

import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "module",
    [
        "immich_memories.tracking.timed",
        "immich_memories.processing.output_contract",
        "immich_memories.api.asset_service",
    ],
)
def test_timed_modules_load_without_sqlalchemy(module):
    # WHY a fresh interpreter: coverage drops every module a dotted --cov target imports
    # while it locates that target; a compiled SQLAlchemy extension then outlives its
    # Python modules and the next cache key fails with "'InternalTraversal' object is not
    # callable". Keeping SQLAlchemy out of these imports keeps that window empty.
    probe = f"import sys, {module}; print('sqlalchemy' in sys.modules)"
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"
