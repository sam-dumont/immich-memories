"""`runs upload` sends a finished run's film to Immich without rendering it again."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

from click.testing import CliRunner

from immich_memories.config_loader import Config
from immich_memories.db import open_store
from immich_memories.tracking.models import RunMetadata
from immich_memories.tracking.run_database import RunDatabase

RUN = "20261007_090000_aaaa"


class FakeImmich:
    def __init__(self, missing=()):
        self.missing = tuple(missing)
        self.uploads: list = []

    def get_key_capabilities(self):
        return SimpleNamespace(missing_upload=self.missing)

    def upload_memory(self, video_path, album_name=None, *, captured_at=None):
        self.uploads.append((video_path, album_name))
        return {"asset_id": "asset-9", "delivery_complete": True, "warnings": []}


def _run(tmp_path, *, film=True) -> Config:
    config = Config()
    config.immich.url = "https://immich.example"
    path = tmp_path / "film.mp4"
    if film:
        path.write_bytes(b"film")
    db = RunDatabase(open_store(config))
    db.save_run(
        RunMetadata(run_id=RUN, created_at=datetime(2026, 10, 7, tzinfo=UTC), status="running")
    )
    db.complete_artifact(
        RUN,
        completed_at=datetime(2026, 10, 7, tzinfo=UTC),
        output_path=str(path),
        output_size_bytes=4,
        output_duration_seconds=30.0,
        delivery_requested=False,
        delivery_album=None,
        warnings=[],
        clips_analyzed=1,
        clips_selected=1,
        errors_count=0,
    )
    return config


def _invoke(config: Config, fake: FakeImmich, *args: str):
    from immich_memories.cli import main

    @contextmanager
    def client(_config):
        yield fake

    # WHY: the CLI group loads the user's real config; Immich is the external boundary (the write).
    with (
        patch("immich_memories.cli.init_config_dir"),
        patch("immich_memories.cli.get_config", return_value=config),
        patch("immich_memories.config.get_config", return_value=config),
        patch("immich_memories.cli.runs_upload.immich_client", client),
    ):
        return CliRunner().invoke(main, ["runs", "upload", *args], catch_exceptions=False)


def test_upload_sends_the_existing_film_to_the_album_and_prints_the_asset(tmp_path):
    config = _run(tmp_path)
    fake = FakeImmich()

    result = _invoke(config, fake, RUN, "--album", "Summer")

    assert result.exit_code == 0
    assert fake.uploads == [(tmp_path / "film.mp4", "Summer")]
    assert "asset-9" in result.output
    assert RunDatabase(open_store(config)).get_run(RUN).immich_asset_id == "asset-9"


def test_upload_says_why_when_the_key_cannot_upload(tmp_path):
    config = _run(tmp_path)
    fake = FakeImmich(missing=["asset.upload"])

    result = _invoke(config, fake, RUN)

    assert result.exit_code == 1
    assert "asset.upload" in result.output
    assert fake.uploads == []


def test_upload_says_so_when_the_film_file_is_gone(tmp_path):
    config = _run(tmp_path, film=False)

    result = _invoke(config, FakeImmich(), RUN)

    assert result.exit_code == 1
    assert "film file is gone" in result.output


def test_upload_of_a_cut_that_was_never_rendered_says_to_render_it(tmp_path):
    config = Config()
    config.immich.url = "https://immich.example"
    RunDatabase(open_store(config)).save_run(
        RunMetadata(run_id=RUN, created_at=datetime(2026, 10, 7, tzinfo=UTC), status="completed")
    )

    result = _invoke(config, FakeImmich(), RUN)

    assert result.exit_code == 1
    assert "never rendered" in result.output
    assert f"runs render {RUN}" in result.output
    assert "gone" not in result.output
