"""UI language selection uses the browser, independently of film settings."""

import importlib.util
from pathlib import Path

from immich_memories.i18n import resolve_ui_locale


def _web_client_labels():
    """The labels the catalogue script extracts from the Svelte client, the one list it keeps."""
    script = Path(__file__).resolve().parents[1] / "scripts" / "update-ui-catalogues.py"
    spec = importlib.util.spec_from_file_location("update_ui_catalogues", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return list(module._web_labels())


def test_browser_language_respects_quality_and_supported_regional_variants():
    assert resolve_ui_locale("de;q=0.4,fr-CA;q=0.9,en;q=0.5") == "fr"
    assert resolve_ui_locale("pt-BR,pt;q=0.9") == "pt-BR"
    assert resolve_ui_locale("zh-CN,ja;q=0.5") == "zh-Hans"
    assert resolve_ui_locale("fr;q=0,en;q=0.8") == "en"
    assert resolve_ui_locale("xx,ru;q=0.7") == "ru"


def test_saved_ui_preference_overrides_browser_and_auto_restores_it():
    assert resolve_ui_locale("fr", preference="de") == "de"
    assert resolve_ui_locale("fr", preference="auto") == "fr"
    assert resolve_ui_locale("fr", preference="unsupported") == "fr"


def test_every_offered_language_has_complete_ui_templates_with_matching_placeholders():
    from string import Formatter

    from babel.messages.pofile import read_po

    from immich_memories.i18n import LOCALES_DIR, SUPPORTED_LOCALES

    messages = {message for _, _, message in _web_client_labels()}
    for locale in SUPPORTED_LOCALES:
        path = LOCALES_DIR / locale.replace("-", "_") / "LC_MESSAGES/ui.po"
        with path.open("rb") as handle:
            catalogue = read_po(handle, locale=locale.replace("-", "_"))
        assert messages, "No interface labels were extracted"
        if locale != "en":
            assert catalogue["Memory"].string != "Memory", locale
        for message in messages:
            entry = catalogue.get(message)
            assert entry and entry.string and "fuzzy" not in entry.flags, (locale, message)
            assert {
                (field, spec, conversion)
                for _, field, spec, conversion in Formatter().parse(message)
                if field is not None
            } == {
                (field, spec, conversion)
                for _, field, spec, conversion in Formatter().parse(entry.string)
                if field is not None
            }, (locale, message)
