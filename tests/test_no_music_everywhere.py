"""No music is a choice on every surface: `audio.no_music`, the web render panel, automation.

It used to be a CLI flag only (`--no-music`). The config key is now the rule `generate`,
`runs render`, the web render panel and automation all start from; a run that asks for
music (`--music`, a track picked in the panel) still gets it.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from immich_memories.automation.candidates import CandidateCategory, MemoryCandidate
from immich_memories.automation.generation_request import GenerationRequest
from immich_memories.cli import main
from immich_memories.config.loader import Config, set_config
from immich_memories.generate_music import music_turned_off
from immich_memories.web.job_routes import RenderOptions
from tests.web_api_fixtures import api_client, config_in


def _automation_argv() -> list[str]:
    candidate = MemoryCandidate(
        memory_type="monthly_highlights",
        category=CandidateCategory.MONTHLY_REVIEW,
        date_range_start=date(2025, 6, 1),
        date_range_end=date(2025, 6, 30),
        person_names=[],
        memory_key="key:monthly",
        score=0.75,
        reason="test candidate",
        asset_count=100,
    )
    argv = GenerationRequest.from_candidate(candidate, upload=False).to_argv()
    return argv[argv.index("generate") :]


def _generate_reads(argv: list[str], config: Config) -> bool:
    """Whether `generate` renders these argv without music: the CLI's own parsing, Immich faked."""
    config.immich.url = "http://immich.test:2283"
    config.immich.api_key = "test-key"
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.get_photos_for_date_range.return_value = []
    # WHY: the CLI's outside boundaries (home, Immich, the render), each named below.
    with (
        # WHY: init_config_dir and get_config would read the real home and config file.
        patch("immich_memories.cli.init_config_dir"),
        # WHY: get_config reads the config file from the real home.
        patch("immich_memories.cli.get_config", return_value=config),
        # WHY: SyncImmichClient is the Immich HTTP client this CLI path would otherwise call.
        patch("immich_memories.api.immich.SyncImmichClient", return_value=client),
        # WHY: fetch_media lists videos from Immich.
        patch(
            "immich_memories.cli.generate.fetch_media",
            return_value=([MagicMock(duration_seconds=10.0)], []),
        ),
        # WHY: the render itself; this test reads what the CLI hands it.
        patch(
            "immich_memories.cli.generate.run_pipeline_and_generate",
            return_value=(Path("plan.mp4"), False, None),
        ) as render,
    ):
        result = CliRunner().invoke(main, [*argv, "--dry-run"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    return render.call_args.kwargs["no_music"]


@pytest.mark.parametrize("off", [True, False])
def test_web_cli_and_automation_start_from_the_same_music_default(tmp_path, off):
    config = config_in(tmp_path)
    config.audio.no_music = off
    set_config(config)
    try:
        session = api_client(config).get("/api/v1/session").json()
    finally:
        set_config(None)

    assert session["music_off"] is off  # the render panel opens on No music
    panel = RenderOptions(music="none" if session["music_off"] else "auto").flags()
    assert music_turned_off(config, music=_flag(panel), no_music="--no-music" in panel) is off
    assert _generate_reads(["generate", "--year", "2025", "--month", "6"], config) is off
    assert _generate_reads(_automation_argv(), config) is off


def _flag(argv: list[str]) -> str | None:
    return next((a.split("=", 1)[1] for a in argv if a.startswith("--music=")), None)


def test_a_run_that_asks_for_music_gets_it_despite_the_config():
    config = Config()
    config.audio.no_music = True

    assert music_turned_off(config, music="auto", no_music=False) is False
    assert music_turned_off(config, music="/music/track.mp3", no_music=False) is False
    assert "--music=auto" in RenderOptions(music="auto").flags()


def test_the_flag_still_turns_music_off_when_the_config_has_it_on():
    config = Config()

    assert config.audio.no_music is False
    assert music_turned_off(config, music=None, no_music=True) is True
    assert music_turned_off(config, music=None, no_music=False) is False
