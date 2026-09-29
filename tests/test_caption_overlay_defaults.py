"""Date and place captions follow one rule on every surface: `defaults.add_date` / `add_place`.

The web render panel, `generate`, `runs render` and automation used to disagree (the panel had
both on, the CLI both off, automation no option at all). One config default, on, is what each
surface starts from now, and each can still turn a caption off for one film.
"""

from __future__ import annotations

from datetime import date

import pytest
from click.testing import CliRunner

from immich_memories.automation.candidates import CandidateCategory, MemoryCandidate
from immich_memories.automation.generation_request import GenerationRequest
from immich_memories.cli import main
from immich_memories.config_loader import Config, set_config
from immich_memories.generate_captions import resolve_caption_overlays
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
    return GenerationRequest.from_candidate(candidate, upload=False).to_argv()


def _cli_reads(argv: list[str], config: Config) -> tuple[bool, bool]:
    """What `generate` renders with for these argv: a flag wins, else the config."""
    add_date = True if "--add-date" in argv else False if "--no-add-date" in argv else None
    add_place = True if "--add-place" in argv else False if "--no-add-place" in argv else None
    return resolve_caption_overlays(config, add_date=add_date, add_place=add_place)


@pytest.mark.parametrize("on", [True, False])
def test_web_cli_and_automation_start_from_the_same_caption_default(tmp_path, on):
    config = config_in(tmp_path)
    config.defaults.add_date = config.defaults.add_place = on
    set_config(config)
    try:
        session = api_client(config).get("/api/v1/session").json()
    finally:
        set_config(None)

    web = RenderOptions(
        add_date=session["captions"]["add_date"], add_place=session["captions"]["add_place"]
    ).flags()
    assert _cli_reads([], config) == (on, on)  # generate / runs render with neither flag
    assert _cli_reads(web, config) == (on, on)  # the render panel as it opens
    assert _cli_reads(_automation_argv(), config) == (on, on)


def test_captions_are_on_unless_the_config_or_the_film_says_otherwise():
    config = Config()

    assert (config.defaults.add_date, config.defaults.add_place) == (True, True)
    assert resolve_caption_overlays(config, add_date=False, add_place=None) == (False, True)


@pytest.mark.parametrize("command", [["generate"], ["runs", "render"]])
def test_both_commands_can_turn_a_caption_off_for_one_film(command):
    shown = CliRunner().invoke(main, [*command, "--help"]).output

    assert "--add-date / --no-add-date" in shown
    assert "--add-place / --no-add-place" in shown
