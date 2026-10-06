"""People data follows HOME and the store location, so a test run never reads a real family."""

from __future__ import annotations

from pathlib import Path

from immich_memories.people.evidence_graph import default_evidence_graph_path


def test_the_scan_measurements_follow_the_store_a_run_resolves(monkeypatch, tmp_path: Path) -> None:
    from immich_memories.db import open_store

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    store_dir = open_store().location.sqlite_path.parent

    assert default_evidence_graph_path() == store_dir / "people-graph.json"
    assert tmp_path / ".immich-memories" not in default_evidence_graph_path().parents


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


def test_the_scan_measurements_follow_a_selected_store_not_the_real_home(
    monkeypatch, tmp_path: Path
) -> None:
    """#2151: a store picked by `IMMICH_MEMORIES_DATABASE_URL` keeps the graph beside it.

    Before the fix, `default_evidence_graph_path()` always returned a path under
    `Path.home()`, so a scan against a non-default store still overwrote whatever
    `~/.immich-memories/people-graph.json` already held.
    """
    from immich_memories.db.bootstrap import StoreLocation

    # Never touch the real home, even though the bug being tested is "falls back to it".
    monkeypatch.setenv("HOME", str(tmp_path / "unused-home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "unused-home"))

    other_store_dir = tmp_path / "other-library"
    other_store_dir.mkdir()
    location = StoreLocation(url=f"sqlite:///{other_store_dir / 'store.db'}")

    assert default_evidence_graph_path(location) == other_store_dir / "people-graph.json"
