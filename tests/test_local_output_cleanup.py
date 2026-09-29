"""Deleting a run's local film once Immich holds the durable copy."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from immich_memories.operations.local_output_cleanup import (
    delete_local_output,
    local_output_directory,
)
from immich_memories.tracking.models import RunMetadata


def _run(run_id: str, output_path: Path | None) -> RunMetadata:
    return RunMetadata(
        run_id=run_id,
        created_at=datetime(2026, 9, 29, tzinfo=UTC),
        output_path=str(output_path) if output_path else None,
    )


def test_a_run_directory_named_after_the_run_id_is_found(tmp_path: Path) -> None:
    run_dir = tmp_path / f"memory_{'run-1'}"
    run_dir.mkdir()
    film = run_dir / "memory.mp4"
    film.write_bytes(b"film")

    assert local_output_directory(_run("run-1", film)) == run_dir


def test_a_bare_output_file_with_no_run_directory_has_none(tmp_path: Path) -> None:
    film = tmp_path / "memory.mp4"
    film.write_bytes(b"film")

    assert local_output_directory(_run("run-2", film)) is None


def test_a_run_with_no_output_path_has_no_directory() -> None:
    assert local_output_directory(_run("run-3", None)) is None


def test_deleting_a_run_directory_removes_the_film_and_any_intermediates(tmp_path: Path) -> None:
    run_dir = tmp_path / "memory_run-4"
    run_dir.mkdir()
    (run_dir / "memory.mp4").write_bytes(b"film")
    (run_dir / "run_metadata.json").write_text("{}")

    deleted = delete_local_output(_run("run-4", run_dir / "memory.mp4"))

    assert deleted is True
    assert not run_dir.exists()


def test_deleting_a_bare_output_file_removes_only_the_file(tmp_path: Path) -> None:
    film = tmp_path / "memory.mp4"
    film.write_bytes(b"film")

    deleted = delete_local_output(_run("run-5", film))

    assert deleted is True
    assert not film.exists()
    assert tmp_path.exists()


def test_deleting_an_already_gone_output_is_a_harmless_no_op(tmp_path: Path) -> None:
    run_dir = tmp_path / "memory_run-6"
    # The directory was never created; the run row still names a path inside it.
    assert delete_local_output(_run("run-6", run_dir / "memory.mp4")) is False


def test_a_run_with_no_output_path_has_nothing_to_delete() -> None:
    assert delete_local_output(_run("run-7", None)) is False
