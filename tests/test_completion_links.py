"""A delivered film's notification points to the browser-facing Immich address."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from immich_memories.cli._pipeline_runner import _send_notification
from immich_memories.config_loader import Config
from immich_memories.db import open_store
from immich_memories.operations.run_index import record_run_attempt
from immich_memories.tracking import RunDatabase
from immich_memories.tracking.models import DeliveryStatus, RunMetadata


def test_completed_upload_notification_links_to_the_saved_asset(tmp_path):
    config = Config(
        database={"url": f"sqlite:///{tmp_path / 'store.db'}"},
        immich={"url": "http://immich.internal:2283", "public_url": "https://photos.example.com/"},
        notifications={"enabled": True, "urls": ["ntfy://example.com/test"]},
    )
    store = open_store(config)
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    output = attempt / "film.mp4"
    RunDatabase(store).save_run(
        RunMetadata(
            run_id="completed-film",
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
            status="completed",
            delivery_status=DeliveryStatus.DELIVERED,
            immich_asset_id="00000000-0000-4000-8000-000000000001",
            warnings=["Low disk space on output"],
        )
    )
    record_run_attempt("completed-film", attempt, output, store=store)
    # WHY: the provider send is the external write; config and persisted run reads are real.
    with patch("apprise.Apprise.notify", return_value=True) as send:
        _send_notification(
            config, "monthly_highlights", "completed", 60, str(output), attempt_dir=attempt
        )
    body = send.call_args.kwargs["body"]
    assert "https://photos.example.com/photos/00000000-0000-4000-8000-000000000001" in body
    assert "immich.internal" not in body
    assert "Warning: Low disk space on output" in body


@pytest.mark.parametrize("record", [None, "{}", "broken JSON"])
def test_notification_still_sends_without_saved_upload(tmp_path, record):
    config = Config(
        database={"url": f"sqlite:///{tmp_path / 'store.db'}"},
        notifications={"enabled": True, "urls": ["ntfy://example.com/test"]},
    )
    if record is not None:
        (tmp_path / "run.private.json").write_text(record)
    # WHY: only the notification provider write is replaced.
    with patch("apprise.Apprise.notify", return_value=True) as send:
        _send_notification(
            config,
            "monthly_highlights",
            "completed",
            60,
            str(tmp_path / "film.mp4"),
            attempt_dir=tmp_path,
        )
    assert "Watch in Immich" not in send.call_args.kwargs["body"]
    assert "Output:" in send.call_args.kwargs["body"]
