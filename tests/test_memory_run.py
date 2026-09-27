"""A cut is followed through its attempt tree: the latest attempt, its live numbers and pictures."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from immich_memories.operations.cut_progress import (
    StageProgressWriter,
    StageUpdate,
    live_progress_of,
    read_latest_attempt,
    recent_pictures_of,
)
from immich_memories.operations.editorial_attempt import EditorialAttempt


def test_an_attempt_from_an_earlier_cut_of_the_same_brief_does_not_count(tmp_path: Path) -> None:
    """Sessions cutting the same brief share a key; only attempts started after arming are ours."""
    root = tmp_path / "editorial-runs" / "k"
    with EditorialAttempt(root, request={"key": "k"}):
        pass
    started = datetime.fromisoformat(read_latest_attempt(root)["started_at"])

    assert read_latest_attempt(root, since=started) is not None
    assert read_latest_attempt(root, since=started + timedelta(seconds=1)) is None


def test_a_live_attempt_reads_as_running_and_a_dropped_lease_as_interrupted(
    tmp_path: Path,
) -> None:
    root = tmp_path / "editorial-runs" / "k"
    with EditorialAttempt(root, request={"key": "k"}) as attempt:
        attempt.stage("Editing the memory")
        live = read_latest_attempt(root)
    dropped = read_latest_attempt(root)

    assert live is not None and live["status"] == "running"
    assert live["directory"] == str(attempt.directory)
    assert dropped is not None and dropped["status"] == "incomplete"


def test_no_pointer_means_no_attempt(tmp_path: Path) -> None:
    assert read_latest_attempt(None) is None
    assert read_latest_attempt(tmp_path) is None


def test_the_live_numbers_come_from_the_same_attempt_the_rows_follow(tmp_path: Path) -> None:
    """A reload rejoins the bar and the strip the way it rejoins the rows: through the attempt."""
    root = tmp_path / "editorial-runs" / "k"
    with EditorialAttempt(root, request={"key": "k"}) as attempt:
        writer = StageProgressWriter(lambda: attempt.directory)
        writer.note_asset("asset-1")
        attempt.stage(writer.publish("previews", 2, 9))

        record = read_latest_attempt(root)

    progress = live_progress_of(record)
    assert progress is not None
    assert (progress.label, progress.done, progress.total) == ("previews", 2, 9)
    assert recent_pictures_of(record) == ("asset-1",)
    assert live_progress_of(None) is None


def test_a_stage_that_has_published_nothing_yet_offers_no_numbers(tmp_path: Path) -> None:
    root = tmp_path / "editorial-runs" / "k"
    with EditorialAttempt(root, request={"key": "k"}):
        record = read_latest_attempt(root)

    assert live_progress_of(record) is None
    assert live_progress_of({"status": "running"}) is None


def test_numbers_from_a_stage_the_run_has_left_behind_are_not_offered(tmp_path: Path) -> None:
    """A finished per-asset pass must not leave a full bar under a row doing other work."""
    root = tmp_path / "editorial-runs" / "k"
    with EditorialAttempt(root, request={"key": "k"}) as attempt:
        writer = StageProgressWriter(lambda: attempt.directory)
        attempt.stage(writer.publish("previews", 9, 9))
        still_reporting = read_latest_attempt(root)
        attempt.stage(StageUpdate("Reading the period account"))
        moved_on = read_latest_attempt(root)

    assert live_progress_of(still_reporting) is not None
    assert live_progress_of(moved_on) is None
