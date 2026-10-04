"""title_screens.locale: "auto" must resolve to a real locale before any text
the film draws — the title card, month dividers and location cards alike.

#1958: the default config shipped "auto" straight into every title-text
consumer, so `film_text("auto")` fell back to English for every non-English
host. Captions already resolved this correctly; titles did not.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from unittest.mock import patch

import pytest

from immich_memories.config_loader import Config
from immich_memories.generate import GenerationParams
from immich_memories.generate_settings import build_title_settings
from immich_memories.i18n import SUPPORTED_LOCALES
from immich_memories.i18n_places import localise_place
from immich_memories.titles.text_builder import generate_month_divider_text


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
        params, config = _params(tmp_path)
        with patch("immich_memories.i18n.detect_system_locale", return_value="fr"):
            settings = build_title_settings(params, config, [])
        assert settings is not None
        assert generate_month_divider_text(12, locale=settings.locale) == "Décembre"

    def test_location_card_follows_the_resolved_locale(self, tmp_path):
        params, config = _params(tmp_path)
        with patch("immich_memories.i18n.detect_system_locale", return_value="fr"):
            settings = build_title_settings(params, config, [])
        assert settings is not None
        assert localise_place("Cyprus", settings.locale) == "Chypre"

    @pytest.mark.parametrize("host_locale", SUPPORTED_LOCALES)
    def test_every_supported_host_locale_reaches_the_title_card(self, tmp_path, host_locale):
        params, config = _params(tmp_path)
        with patch("immich_memories.i18n.detect_system_locale", return_value=host_locale):
            settings = build_title_settings(params, config, [])
        assert settings is not None
        assert settings.locale == host_locale

    def test_unsupported_host_falls_back_to_english_title_card(self, tmp_path):
        params, config = _params(tmp_path)
        with patch("immich_memories.i18n.detect_system_locale", return_value="en"):
            settings = build_title_settings(params, config, [])
        assert settings is not None
        assert settings.locale == "en"
        assert settings.title_override == "Christmas"
