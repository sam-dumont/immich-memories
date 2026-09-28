"""People data follows HOME and the store location, so a test run never reads a real family."""

from __future__ import annotations

from pathlib import Path

from immich_memories.people.evidence_graph import default_evidence_graph_path


def test_the_scan_measurements_follow_a_redirected_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    assert default_evidence_graph_path() == tmp_path / ".immich-memories" / "people-graph.json"


def test_the_people_registry_a_test_reads_is_not_the_developers() -> None:
    from immich_memories.db import open_store

    location = open_store().location.sqlite_path

    assert location is not None
    assert Path.home() / ".immich-memories" not in location.parents


def test_launch_environment_redirects_home_at_the_workspace(tmp_path: Path) -> None:
    from tests.e2e.conftest import _build_launch_environment

    environment = _build_launch_environment(tmp_path)

    assert environment["HOME"] == str(tmp_path)
    assert environment["USERPROFILE"] == str(tmp_path)
