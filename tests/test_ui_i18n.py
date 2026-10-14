"""UI language selection uses the browser, independently of film settings."""

import importlib.util
import re
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


def test_catalogue_extraction_finishes_on_an_unterminated_escaped_label(tmp_path):
    import subprocess
    import sys

    root = tmp_path / "web"
    root.mkdir()
    (root / "example.ts").write_text("t('" + "\\a" * 40 + "\n")
    script = Path(__file__).resolve().parents[1] / "scripts" / "update-ui-catalogues.py"
    code = (
        "import runpy; from pathlib import Path; "
        f"module = runpy.run_path({str(script)!r}); "
        f"module['_web_labels'].__globals__['WEB_ROOT'] = Path({str(root)!r}); "
        "assert list(module['_web_labels']()) == []"
    )
    # A backtracking pattern on 40 escaped pairs runs for hours, so a minute still catches it;
    # the budget also covers a cold interpreter and the script's imports on a slow runner.
    subprocess.run([sys.executable, "-c", code], check=True, timeout=60)


def test_every_memory_type_a_detector_proposes_has_a_web_label():
    # WHY: no external boundary; reads source files only. The detectors name their memory_type as a
    # literal, and a missing label would render a suggestion as the generic "Memory".
    root = Path(__file__).resolve().parents[1]
    labels = (root / "web/src/lib/labels.ts").read_text()
    labelled = set(
        re.findall(r"^\s*(\w+): N_\(", labels.split("MEMORY_TYPES")[1].split("};")[0], re.M)
    )
    emitted = {
        match
        for path in (root / "src/immich_memories/automation").glob("*detector*.py")
        for match in re.findall(r'memory_type="(\w+)"', path.read_text())
    }
    assert {"person_monthly", "monthly_backfill", "album", "season", "holiday"} <= emitted
    assert emitted <= labelled, emitted - labelled


def test_a_counted_label_is_extracted_with_its_plural():
    labels = {message for _, _, message in _web_client_labels()}

    assert ("{n} photo", "{n} photos") in labels


def test_labels_the_client_builds_at_run_time_reach_the_catalogue():
    # Run statuses, the run page's views and filters, suggestion outcomes and the refusals
    # the client falls back to were built at run time, so the extractor never saw them.
    labels = {message for _, _, message in _web_client_labels()}

    assert {
        "Completed",
        "Running",
        "Failed",
        "Cancelled",
        "Interrupted",
        "All",
        "Contact sheet",
        "All pictures",
        "Videos",
        "Stills",
        "Skipped",
        "Invalid username or password",
        "Too many failed attempts. Try again later.",
        "Run not found. It may have been removed.",
        "Upload availability could not be checked. The film can still be rendered and downloaded.",
    } <= labels


# Arguments the server words: each is registered with N_() where the server's sentences are
# listed (web/src/lib/labels.ts), since no table in the calling file can name them.
_SERVER_WORDED = {
    ("lib/RenderPanel.svelte", "answer.detail"),
    ("routes/settings/+page.svelte", "body.detail"),
    ("routes/login/+page.svelte", "body.detail"),
    ("routes/runs/[run_id]/+page.svelte", "story.preparation"),
}


def test_every_label_built_at_run_time_comes_from_a_registered_table():
    # WHY: no boundary; reads the client's source. The extractor sees only literal t('...')
    # and N_('...'); t(value) on anything else stays English in every language.
    root = Path(__file__).resolve().parents[1] / "web/src"
    unregistered = []
    for path in sorted(root.rglob("*")):
        if path.suffix not in {".svelte", ".ts"} or path.name in {"api-types.ts", "i18n.svelte.ts"}:
            continue
        source = path.read_text()
        name = str(path.relative_to(root))
        for argument, before in _dynamic_t_arguments(source):
            if (name, argument) in _SERVER_WORDED:
                continue
            table = _table_behind(argument, before)
            if not (table and _is_registered(table, source, root)):
                unregistered.append(f"{name}: t({argument})")
    assert not unregistered, unregistered


def test_the_guard_catches_an_unregistered_label():
    source = "const LABELS = { a: 'Apple' };\nconst x = t(LABELS[key]);\nconst y = t(run.status);"

    assert [
        _table_behind(argument, before) for argument, before in _dynamic_t_arguments(source)
    ] == ["LABELS", None]
    assert not _is_registered("LABELS", source, Path("/nowhere"))


def _dynamic_t_arguments(source: str) -> list[tuple[str, str]]:
    """Each t() whose first argument is not a literal, with the source that comes before it."""
    found = []
    for match in re.finditer(r"(?<![\w.$])t\(", source):
        start = match.end()
        depth, end = 0, start
        while end < len(source):
            char = source[end]
            if char in "([{":
                depth += 1
            elif char in ")]}":
                if depth == 0:
                    break
                depth -= 1
            elif char == "," and depth == 0:
                break
            end += 1
        argument = source[start:end].strip()
        if argument and argument[0] not in "'\"`":
            found.append((argument, source[: match.start()]))
    return found


def _table_behind(argument: str, before: str) -> str | None:
    """The table a dynamic argument reads: `TABLE[key]`, or the nearest loop or const over one."""
    root = re.match(r"[A-Za-z_$][\w$]*", argument)
    if not root:
        return None
    name = root.group(0)
    if argument[len(name) :].startswith("["):
        return name
    sources = list(
        re.finditer(
            rf"#each\s+([A-Za-z_$][\w$]*)\s+as\s+[^}}]*\b{re.escape(name)}\b"
            rf"|\b{re.escape(name)}\s*=\s*([A-Za-z_$][\w$]*)\[",
            before,
        )
    )
    if not sources:
        return None
    return sources[-1].group(1) or sources[-1].group(2)


def _is_registered(table: str, source: str, root: Path) -> bool:
    """The table is defined here or in labels.ts, and every label in it is marked with N_()."""
    for text in (source, (root / "lib/labels.ts").read_text() if root.is_dir() else ""):
        definition = re.search(rf"\bconst\s+{re.escape(table)}\b[^=]*=\s*([\[{{])", text)
        if definition:
            body = text[definition.end() : text.find(";", definition.end())]
            return "N_(" in body and not _bare_words(body)
    return False


def _bare_words(body: str) -> list[str]:
    """Strings in a table that a reader would see but no N_() marks; keys and codes are fine."""
    unmarked = re.sub(r"N_\(\s*(['\"])(?:\\.|(?!\1).)*\1\s*\)", "", body)
    literals = re.finditer(r"(['\"])((?:\\.|(?!\1).)*)\1", unmarked)
    return [
        literal.group(2)
        for literal in literals
        if not re.match(r"\s*:", unmarked[literal.end() :])
        and not re.fullmatch(r"[a-z0-9_-]*", literal.group(2))
    ]
