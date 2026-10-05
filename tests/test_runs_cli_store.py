"""`runs list` and `runs show` against a real store: delivery, and runs whose process is gone."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

from click.testing import CliRunner

from immich_memories.config_loader import Config
from immich_memories.db import open_store
from immich_memories.tracking.models import RunMetadata
from immich_memories.tracking.run_database import RunDatabase

_T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


def _config() -> Config:
    config = Config()
    config.immich.url = "https://immich.example"
    return config


def _cli(config: Config, *args: str) -> str:
    from immich_memories.cli import main

    # WHY: the CLI group loads the user's real config directory on startup.
    with (
        patch("immich_memories.cli.init_config_dir"),
        patch("immich_memories.cli.get_config", return_value=config),
        patch("immich_memories.config.get_config", return_value=config),
    ):
        result = CliRunner().invoke(main, list(args), catch_exceptions=False)
    return result.output


def _delivered_run(db: RunDatabase, run_id: str, output: str) -> None:
    db.save_run(RunMetadata(run_id=run_id, created_at=_T0, status="running"))
    db.complete_artifact(
        run_id,
        completed_at=_T0,
        output_path=output,
        output_size_bytes=1000,
        output_duration_seconds=30.0,
        delivery_requested=True,
        delivery_album="Family films",
        warnings=[],
        clips_analyzed=4,
        clips_selected=4,
        errors_count=0,
    )
    db.mark_delivered(run_id, "asset-delivered")


def test_runs_show_reports_the_immich_delivery(tmp_path) -> None:
    config = _config()
    db = RunDatabase(open_store(config))
    _delivered_run(db, "20260301_090000_aaaa", str(tmp_path / "gone" / "film.mp4"))

    printed = _cli(config, "runs", "show", "20260301_090000_aaaa")

    assert "delivered" in printed
    assert "Family films" in printed
    assert "https://immich.example/photos/asset-delivered" in printed
    assert "removed" in printed, "the local file was reclaimed after delivery; say so"


def test_runs_list_shows_a_run_whose_process_died_as_interrupted() -> None:
    config = _config()
    db = RunDatabase(open_store(config))
    db.save_run(RunMetadata(run_id="20260301_090000_dead", created_at=_T0, status="running"))

    printed = _cli(config, "runs", "list")

    assert "│ interrupted" in printed
    dead = db.get_run("20260301_090000_dead")
    assert dead is not None and dead.status == "interrupted"


def test_runs_list_keeps_a_live_run_running() -> None:
    from immich_memories.tracking.run_tracker import RunTracker

    config = _config()
    live = RunTracker(store=open_store(config), capture_system=False)
    live.start_run()

    printed = _cli(config, "runs", "list")

    assert "│ running" in printed
    live.complete_run()
