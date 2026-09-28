"""UI language selection uses the browser, independently of film settings."""

from immich_memories.ui.i18n import resolve_ui_locale


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


def test_interface_catalogue_formats_values_and_falls_back_for_unknown_messages():
    from immich_memories.ui.i18n import tr

    assert tr("Memory", locale_code="fr") == "Souvenir"
    assert (
        tr("Connected as: {name}", locale_code="fr", name="Camille")
        == "Connecté en tant que : Camille"
    )
    assert tr("An untranslated message", locale_code="fr") == "An untranslated message"
    assert tr("Memory", locale_code="unsupported") == "Memory"


def test_translated_choices_keep_the_values_the_pipeline_expects():
    from immich_memories.ui.i18n import tr_options

    assert tr_options({"memory": "Memory"}, locale_code="fr") == {"memory": "Souvenir"}
    assert tr_options(["Memory"], locale_code="fr") == {"Memory": "Souvenir"}


def test_every_offered_language_has_complete_ui_templates_with_matching_placeholders():
    from babel.messages.extract import extract_from_dir
    from babel.messages.pofile import read_po

    from immich_memories.i18n import LOCALES_DIR, SUPPORTED_LOCALES

    messages = {
        message
        for _, _, message, _, _ in extract_from_dir(
            str(LOCALES_DIR.parent / "ui"), keywords={"tr": (1,), "N_": (1,), "tr_plural": (1, 2)}
        )
    }
    for locale in SUPPORTED_LOCALES:
        path = LOCALES_DIR / locale.replace("-", "_") / "LC_MESSAGES/ui.po"
        with path.open("rb") as handle:
            catalogue = read_po(handle, locale=locale.replace("-", "_"))
        assert messages, "No interface labels were extracted"
        if locale != "en":
            assert catalogue["Memory"].string != "Memory", locale
        for message in messages:
            entry = catalogue.get(message[0] if isinstance(message, tuple) else message)
            forms = (
                entry.string if entry and isinstance(message, tuple) else (entry and entry.string,)
            )
            assert entry and all(forms) and "fuzzy" not in entry.flags, (locale, message)
            if isinstance(message, tuple):
                assert len(forms) == catalogue.num_plurals, (locale, message)
            source = message[-1] if isinstance(message, tuple) else message
            for form in forms:
                assert _fields(source) == _fields(form), (locale, message)


def _fields(template: str) -> set[tuple]:
    from string import Formatter

    return {
        (field, spec, conversion)
        for _, field, spec, conversion in Formatter().parse(template)
        if field is not None
    }


def test_counts_follow_each_locales_plural_rule():
    from immich_memories.ui.i18n import tr_plural

    def keys(n: int, locale: str) -> str:
        return tr_plural(
            "{title}  ({n} key)", "{title}  ({n} keys)", n, title="Preset", locale_code=locale
        )

    assert [keys(n, "en") for n in (1, 2)] == ["Preset  (1 key)", "Preset  (2 keys)"]
    assert [keys(n, "ru") for n in (1, 3, 5)] == [
        "Preset  (1 ключ)",
        "Preset  (3 ключа)",
        "Preset  (5 ключей)",
    ]
