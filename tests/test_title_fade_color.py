"""Only supported film edge colors can enter the render configuration."""

import pytest
from pydantic import ValidationError

from immich_memories.config_models_render import TitleScreenConfig


def test_title_config_rejects_unsupported_edge_color():
    with pytest.raises(ValidationError, match="fade_color"):
        TitleScreenConfig.model_validate({"fade_color": "red"})


@pytest.mark.parametrize("color", ["white", "black"])
def test_configured_fade_survives_generation_settings(color, tmp_path):
    from datetime import date

    from immich_memories.config_loader import Config
    from immich_memories.generate import GenerationParams
    from immich_memories.generate_settings import build_title_settings

    config = Config.model_validate({"title_screens": {"fade_color": color}})
    params = GenerationParams(
        clips=[],
        output_path=tmp_path / "memory.mp4",
        config=config,
        memory_type="year",
        date_start=date(2026, 1, 1),
        date_end=date(2026, 12, 31),
    )
    settings = build_title_settings(params, config, [])
    assert settings is not None
    assert settings.fade_color == color
