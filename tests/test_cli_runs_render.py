"""`runs render` renders a saved cut or one of its revisions, with generate's output flags."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from immich_memories.cli import main
from immich_memories.operations.cut_revisions import CutEdits, save_revision
from tests.web_api_fixtures import config_in, save_run

RUN = "20260927_080000_cafe"


def _config(tmp_path):
    config = config_in(tmp_path)
    config.immich.url = "http://immich.invalid"
    config.immich.api_key = "unit-test-key"
    return config


def _invoke(config, args, rendered):
    def render(**kwargs):
        rendered.append(kwargs)
        return Path("/films/june.mp4")

    # WHY: render_saved_cut writes the film; the CLI tier checks what it asks for.
    # WHY: `runs` reads the real config file from $HOME otherwise.
    with (
        patch("immich_memories.cli.init_config_dir"),
        patch("immich_memories.cli.get_config", return_value=config),
        patch("immich_memories.config.get_config", return_value=config),
        patch("immich_memories.cli.runs_render.render_saved_cut", render),
    ):
        return CliRunner().invoke(main, args, catch_exceptions=False)


def test_runs_render_takes_the_chosen_revision_and_generate_s_output_flags(tmp_path):
    config = _config(tmp_path)
    attempt = save_run(config, RUN)
    save_revision(attempt, CutEdits(removed=("garden-1",)))
    rendered: list[dict] = []

    result = _invoke(
        config,
        [
            "runs",
            "render",
            RUN,
            "--revision",
            "1",
            "--no-music",
            "--title",
            "June",
            "--format",
            "mov",
        ],
        rendered,
    )

    assert result.exit_code == 0, result.output
    (call,) = rendered
    assert call["attempt_dir"] == attempt
    assert call["revision"].number == 1
    assert call["revision"].edits.removed == ("garden-1",)
    assert call["request"].no_music is True
    assert call["request"].title == "June"
    assert call["request"].output_format == "mov"
    assert "/films/june.mp4" in result.output


def test_runs_render_without_a_revision_renders_the_cut_and_names_a_missing_one(tmp_path):
    config = _config(tmp_path)
    save_run(config, RUN)
    rendered: list[dict] = []

    assert _invoke(config, ["runs", "render", RUN], rendered).exit_code == 0
    assert rendered[0]["revision"] is None
    missing = _invoke(config, ["runs", "render", RUN, "--revision", "4"], rendered)
    assert missing.exit_code != 0
    assert "no revision 4" in missing.output
