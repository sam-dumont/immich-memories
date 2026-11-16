"""`runs label` writes a delivered film's label to Immich again without rendering (#2627)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import patch

from click.testing import CliRunner

from immich_memories.api.album_service import upload_waits
from immich_memories.api.film_relabel import RelabelOutcome, RelabelStatus
from immich_memories.config.loader import Config
from immich_memories.db import open_store
from immich_memories.tracking.models import RunMetadata
from immich_memories.tracking.run_database import RunDatabase
from tests.immich_fakes import fake_immich_client

# Placeholder asset ids; no real library is involved.
ASSETS = {
    "20261001_090000_aaaa": "asset-one",
    "20261002_090000_bbbb": "asset-two",
    "20261003_090000_cccc": "asset-three",
    "20261004_090000_dddd": "asset-four",
}


def _config(*, delivered: dict[str, str | None] | None = None, size: int = 2_000_000_000) -> Config:
    config = Config()
    config.immich.url = "https://immich.example"
    db = RunDatabase(open_store(config))
    for run_id, asset in (delivered if delivered is not None else ASSETS).items():
        db.save_run(
            RunMetadata(
                run_id=run_id,
                created_at=datetime(2026, 10, 1, tzinfo=UTC),
                status="completed",
                memory_type="monthly_highlights",
                output_size_bytes=size,
                app_version="1.0.0",
                immich_asset_id=asset,
            )
        )
    return config


def _invoke(config: Config, client, *args: str):
    from immich_memories.cli import main

    @contextmanager
    def opened(_config):
        yield client

    # WHY: the CLI group loads the user's real config; Immich is the external boundary.
    with (
        patch("immich_memories.cli.init_config_dir"),
        patch("immich_memories.cli.get_config", return_value=config),
        patch("immich_memories.config.get_config", return_value=config),
        patch("immich_memories.cli.runs_label.immich_client", opened),
    ):
        return CliRunner().invoke(main, ["runs", "label", *args], catch_exceptions=False)


def _client(by_asset: dict[str, RelabelOutcome]):
    client = fake_immich_client()
    client.relabel_film.side_effect = lambda asset_id, _label, **_: by_asset[asset_id]
    return client


def test_a_run_is_relabelled_on_the_asset_it_was_delivered_as_with_waits_sized_from_the_film():
    config = _config()
    client = _client({"asset-one": RelabelOutcome(RelabelStatus.WRITTEN, removed=("old/tag",))})

    result = _invoke(config, client, "20261001_090000_aaaa")

    assert result.exit_code == 0
    assert "written" in result.output and "old/tag" in result.output
    (call,) = client.relabel_film.call_args_list
    assert call.args[0] == "asset-one"
    assert call.kwargs["waits"] == upload_waits(2_000_000_000)
    # The same label an upload builds, from the stored run: the provenance release is the run's.
    assert "immich-memories/version/1.0.0" in call.args[1].tags


def test_all_skips_what_already_matches_and_reports_every_outcome():
    config = _config()
    client = _client(
        {
            "asset-one": RelabelOutcome(RelabelStatus.WRITTEN),
            "asset-two": RelabelOutcome(RelabelStatus.UNCHANGED),
            "asset-three": RelabelOutcome(RelabelStatus.ASSET_GONE),
            "asset-four": RelabelOutcome(
                RelabelStatus.WRITTEN, warnings=("the film's tags did not stay",)
            ),
        }
    )

    result = _invoke(config, client, "--all")

    out = result.output
    assert "20261002_090000_bbbb: unchanged" in out
    assert "20261003_090000_cccc: asset gone from Immich" in out
    assert "20261001_090000_aaaa: written" in out
    assert "the film's tags did not stay" in out
    assert result.exit_code == 1  # a label that did not stay is not a success


def test_all_with_a_key_that_lacks_the_rights_reports_it_per_run_and_fails():
    config = _config(delivered={"20261001_090000_aaaa": "asset-one"})
    client = _client(
        {"asset-one": RelabelOutcome(RelabelStatus.RIGHTS_MISSING, "the key lacks tag.asset")}
    )

    result = _invoke(config, client, "--all")

    assert "rights missing" in result.output and "tag.asset" in result.output
    assert result.exit_code == 1


def test_a_run_whose_film_is_gone_from_immich_is_refused_clearly():
    config = _config()
    client = _client({"asset-one": RelabelOutcome(RelabelStatus.ASSET_GONE)})

    result = _invoke(config, client, "20261001_090000_aaaa")

    assert result.exit_code == 1
    assert "asset gone" in result.output


def test_a_run_never_delivered_is_refused_and_nothing_is_sent():
    config = _config(delivered={"20261001_090000_aaaa": None})
    client = _client({})

    result = _invoke(config, client, "20261001_090000_aaaa")

    assert result.exit_code == 1
    assert "never delivered" in result.output
    client.relabel_film.assert_not_called()


def test_an_unknown_run_is_refused():
    result = _invoke(_config(), _client({}), "nope")

    assert result.exit_code == 1
    assert "Run not found" in result.output


def test_a_run_id_or_all_is_needed_but_not_both():
    config = _config()

    assert _invoke(config, _client({})).exit_code == 2
    assert _invoke(config, _client({}), "20261001_090000_aaaa", "--all").exit_code == 2


def test_an_immich_error_on_one_run_does_not_stop_the_others():
    config = _config(
        delivered={"20261001_090000_aaaa": "asset-one", "20261002_090000_bbbb": "asset-two"}
    )
    client = fake_immich_client()

    def relabel(asset_id, label, *, waits):
        if asset_id == "asset-one":
            raise RuntimeError("secret-host.example refused")
        return RelabelOutcome(RelabelStatus.WRITTEN)

    client.relabel_film.side_effect = relabel

    result = _invoke(config, client, "--all")

    assert "20261001_090000_aaaa: failed" in result.output
    assert "20261002_090000_bbbb: written" in result.output
    assert "secret-host.example" not in result.output
