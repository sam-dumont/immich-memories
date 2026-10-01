"""A fresh generation's fade override stays local to that invocation."""

from unittest.mock import patch

from click.testing import CliRunner

from immich_memories.cli import main
from immich_memories.config_loader import Config


def test_generate_applies_fade_before_planning_without_mutating_defaults():
    config = Config()
    seen = []

    def stop_before_selection(given, sharing, fade_color):
        apply_overrides(given, sharing, fade_color)
        seen.append(given.title_screens.fade_color)
        raise SystemExit(0)

    from immich_memories.cli.generate import _apply_run_overrides as apply_overrides

    with (
        # WHY: avoid creating configuration files in the owner's home.
        patch("immich_memories.cli.init_config_dir"),
        patch("immich_memories.cli.get_config", return_value=config),
        # WHY: stop before media selection or rendering; capture the configuration they receive.
        patch("immich_memories.cli.generate._apply_run_overrides", stop_before_selection),
    ):
        result = CliRunner().invoke(main, ["generate", "--year", "2025", "--fade-color", "black"])

    assert result.exit_code == 0, result.output
    assert seen == ["black"]
    assert config.title_screens.fade_color == "white"


def test_title_preview_uses_the_saved_fade_default(tmp_path):
    config = Config()
    config.title_screens.fade_color = "black"
    seen = []

    def record_preview(*, config, style, output_dir):
        from unittest.mock import MagicMock

        seen.append(config.fade_color)
        return MagicMock()

    with (
        # WHY: keep configuration writes away from the owner's home.
        patch("immich_memories.cli.init_config_dir"),
        patch("immich_memories.cli.get_config", return_value=config),
        # WHY: the preview writes a video; its pixels are checked by the FFmpeg title tests.
        patch("immich_memories.titles.TitleScreenGenerator", record_preview),
    ):
        result = CliRunner().invoke(
            main, ["titles", "test", "--year", "2025", "--output", str(tmp_path / "preview.mp4")]
        )

    assert result.exit_code == 0, result.output
    assert seen == ["black"]
