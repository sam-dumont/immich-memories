"""title_screens.locale: "auto" must resolve to a real locale before any text
the film draws — the title card, month dividers and location cards alike.

#1958: the default config shipped "auto" straight into every title-text
consumer, so `film_text("auto")` fell back to English for every non-English
host. Captions already resolved this correctly; titles did not.
"""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from immich_memories.config_loader import Config
from immich_memories.generate import GenerationParams
from immich_memories.generate_settings import build_title_settings
from immich_memories.i18n import SUPPORTED_LOCALES, get_month_name
from immich_memories.processing.assembly_config import TitleScreenSettings
from immich_memories.processing.title_divider_planner import TitleDividerPlanner
from immich_memories.titles.text_builder import generate_month_divider_text

_NO_HOST_PREFERENCE = {"LC_ALL": "", "LC_MESSAGES": "", "LANG": "", "LANGUAGE": ""}


def _params(tmp_path) -> tuple[GenerationParams, Config]:
    config = Config.model_validate({})
    params = GenerationParams(
        clips=[],
        output_path=tmp_path / "memory.mp4",
        config=config,
        memory_type="holiday",
        date_start=date(2026, 12, 20),
        date_end=date(2026, 12, 25),
        memory_preset_params={"holiday": "christmas"},
    )
    return params, config


class TestTitleLocaleAuto:
    def test_default_config_locale_is_auto(self):
        # The defect lives in what happens to this default; pin it so a config
        # change does not silently stop exercising the "auto" path.
        assert Config.model_validate({}).title_screens.locale == "auto"

    def test_title_card_follows_the_french_host(self, tmp_path):
        params, config = _params(tmp_path)
        # WHY: detect_system_locale is the host-locale boundary; mocking it is
        # how the test asks for a French host without touching the real OS locale.
        with patch("immich_memories.i18n.detect_system_locale", return_value="fr"):
            settings = build_title_settings(params, config, [])
        assert settings is not None
        assert settings.locale == "fr"
        assert settings.title_override == "Noël"

    def test_explicit_locale_is_unaffected_by_the_host(self, tmp_path):
        config = Config.model_validate({"title_screens": {"locale": "fr"}})
        params, _ = _params(tmp_path)
        params = replace(params, config=config)
        with patch("immich_memories.i18n.detect_system_locale") as detect:
            settings = build_title_settings(params, config, [])
            detect.assert_not_called()
        assert settings is not None
        assert settings.locale == "fr"
        assert settings.title_override == "Noël"

    def test_month_divider_follows_the_resolved_locale(self, tmp_path):
        """Drives the real TitleScreenGenerator, not just the text helper."""
        params, config = _params(tmp_path)
        with patch("immich_memories.i18n.detect_system_locale", return_value="fr"):
            settings = build_title_settings(params, config, [])
        assert settings is not None

        from immich_memories.titles.generator import TitleScreenConfig, TitleScreenGenerator

        gen_config = TitleScreenConfig(locale=settings.locale)
        with (
            # WHY: RenderingService/EndingService/TripService each reach for
            # FFmpeg, GPU detection or map tiles in __init__; mocked so only
            # the divider text, the thing under test, is real.
            patch("immich_memories.titles.generator.RenderingService") as rendering_cls,
            patch("immich_memories.titles.generator.EndingService"),
            patch("immich_memories.titles.generator.TripService"),
        ):
            rendering = rendering_cls.return_value
            rendering.use_gpu = False
            generator = TitleScreenGenerator(config=gen_config, output_dir=tmp_path)
            generator.generate_month_divider(month=12)

        assert rendering.create_title_video.call_args.kwargs["title"] == "Décembre"

    def test_location_card_follows_the_resolved_locale(self, tmp_path):
        """Drives the real TitleDividerPlanner, not just the i18n helper."""
        params, config = _params(tmp_path)
        with patch("immich_memories.i18n.detect_system_locale", return_value="fr"):
            settings = build_title_settings(params, config, [])
        assert settings is not None

        asked: list[str] = []

        class _Generator:
            def generate_location_card_screen(self, name, lat=None, lon=None):
                asked.append(name)
                return type("Screen", (), {"path": Path("card.mp4")})()

        planner = TitleDividerPlanner(
            _Generator(),  # type: ignore[arg-type]
            TitleScreenSettings(locale=settings.locale),
        )
        planner.make_location_card_clip("Nicosia, Cyprus", {})

        assert asked == ["Nicosia, Chypre"]

    @pytest.mark.parametrize("host_locale", SUPPORTED_LOCALES)
    def test_every_supported_host_locale_renders_its_own_month_divider(self, tmp_path, host_locale):
        params, config = _params(tmp_path)
        with patch("immich_memories.i18n.detect_system_locale", return_value=host_locale):
            settings = build_title_settings(params, config, [])
        assert settings is not None
        assert settings.locale == host_locale
        # Independent oracle: get_month_name, not the divider-text helper under test.
        assert generate_month_divider_text(12, locale=settings.locale) == get_month_name(
            12, host_locale
        )

    def test_unsupported_host_falls_back_to_english_title_card(self, tmp_path):
        params, config = _params(tmp_path)
        # An actually-unsupported host locale, read through the real env
        # boundary detect_system_locale parses — not a mocked return value.
        with patch.dict(os.environ, {**_NO_HOST_PREFERENCE, "LANG": "xx_YY"}, clear=False):
            settings = build_title_settings(params, config, [])
        assert settings is not None
        assert settings.locale == "en"
        assert settings.title_override == "Christmas"
