"""`generate --accounts` names the Immich accounts a film reads (#1500 slice 7).

Without the flag the primary reads alone. The Immich server is the two-account fake of
`tests/household_fake.py`, so every request the CLI makes is a real HTTP call to it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from immich_memories.cli._editorial_context import build_editorial_context
from immich_memories.cli._run_inputs import ResolvedRunInputs
from immich_memories.config_loader import Config
from immich_memories.timeperiod import DateRange
from tests.household_fake import PARTNER_KEY, PRIMARY_KEY, FakeHousehold, immich_config, picture

JUNE = DateRange(datetime(2025, 6, 1, tzinfo=UTC), datetime(2025, 6, 30, 23, 59, tzinfo=UTC))


@pytest.fixture
def immich(monkeypatch) -> FakeHousehold:
    server = FakeHousehold(
        library={
            PRIMARY_KEY: [picture("p-park", "primary", 2, ("alex-p",))],
            PARTNER_KEY: [picture("q-lake", "partner", 5, ("alex-q",))],
        },
        roster={PRIMARY_KEY: [{"id": "alex-p", "name": "Alex"}]},
    )
    return server.install(monkeypatch)


def _generate(tmp_path, *args):
    from immich_memories.cli import main

    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"immich": immich_config()}))
    with (
        # WHY: init_config_dir would create a real config dir under the user's home.
        patch("immich_memories.cli.init_config_dir"),
        # WHY: the pipeline renders and uploads; the test inspects what it was handed.
        patch(
            "immich_memories.cli.generate.run_pipeline_and_generate",
            return_value=(tmp_path / "out.mp4", False, None),
        ) as pipeline,
    ):
        result = CliRunner().invoke(
            main,
            [
                *("-c", str(config), "generate", "--quiet", "--year", "2025", "--month", "6"),
                *("--include-photos", "--no-live-photos", "--no-music", *args),
            ],
        )
    return result, pipeline


def test_the_primary_reads_alone_without_the_flag(tmp_path, immich):
    result, pipeline = _generate(tmp_path)

    assert result.exit_code == 0, (result.output, result.exception)
    kwargs = pipeline.call_args.kwargs
    assert [photo.id for photo in kwargs["photo_assets"]] == ["p-park"]
    assert "accounts" not in kwargs["memory_preset_params"]
    assert not any(path.endswith("/users/me") for path in immich.requests)


def test_named_accounts_are_read_and_travel_to_the_editor(tmp_path, immich):
    result, pipeline = _generate(tmp_path, "--accounts", " primary , partner ")

    assert result.exit_code == 0, (result.output, result.exception)
    kwargs = pipeline.call_args.kwargs
    assert sorted(photo.id for photo in kwargs["photo_assets"]) == ["p-park", "q-lake"]
    assert kwargs["memory_preset_params"]["accounts"] == ["primary", "partner"]


def test_the_primary_named_alone_is_the_one_account_run(tmp_path, immich):
    result, pipeline = _generate(tmp_path, "--accounts", "primary")

    assert result.exit_code == 0, (result.output, result.exception)
    assert "accounts" not in pipeline.call_args.kwargs["memory_preset_params"]


def test_an_unknown_account_fails_before_any_request(tmp_path, immich):
    result, pipeline = _generate(tmp_path, "--accounts", "primary,uncle")

    assert result.exit_code == 2
    assert "'uncle' is not configured" in result.output
    assert immich.requests == []
    pipeline.assert_not_called()


def test_a_trip_refuses_extra_accounts(tmp_path, immich):
    result, pipeline = _generate(tmp_path, "--accounts", "partner", "--memory-type", "trip")

    assert result.exit_code == 2
    assert "not albums or trips" in result.output
    pipeline.assert_not_called()


@pytest.mark.parametrize(
    ("params", "accounts"),
    [({}, ()), ({"accounts": ["primary", "partner"]}, ("primary", "partner"))],
)
def test_the_run_context_reads_the_accounts_the_run_named(params, accounts):
    config = Config()
    resolved = ResolvedRunInputs.from_arguments(
        include_photos=True,
        photo_assets=None,
        dry_run=False,
        automation_attempt_id=None,
        upload_to_immich=False,
        config=config,
        person_names=[],
        music=None,
        memory_preset_params=params,
    )
    context = build_editorial_context(
        resolved=resolved,
        config=config,
        memory_type="monthly_highlights",
        memory_key=None,
        output_stem="june",
        assets=[],
        date_range=JUNE,
        date_ranges=None,
        duration=60.0,
        transition="smart",
        title_override=None,
        person_names=[],
        accept_any_provenance=False,
    )

    assert context.accounts == accounts
