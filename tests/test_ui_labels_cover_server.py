"""The client words every setting and relationship the server can send (#1965).

The server sends keys (`llm.model`, `parent-of`); `settingLabels.ts` and
`people/relationshipLabels.ts` word them through the UI catalogue. A key missing from a table
would show as raw text in every language, so the keys the server can emit are enumerated here.
"""

from __future__ import annotations

import re
from pathlib import Path

from babel.messages.pofile import read_po

from immich_memories.config import Config
from immich_memories.config.sources import describe_settings
from immich_memories.i18n import LOCALES_DIR, SUPPORTED_LOCALES
from immich_memories.people import relationships
from immich_memories.people.editor import _chain_steps
from immich_memories.people.kinship import Hop, Suggestion

WEB = Path(__file__).resolve().parents[1] / "web/src/lib"


def _table(path: str, name: str) -> dict[str, str]:
    """The `key: N_('English')` rows of one label table, English unescaped."""
    text = (WEB / path).read_text()
    body = text.split(f"const {name}", 1)[1].split("\n};", 1)[0]
    rows = re.findall(r"""^\s*'?([\w.-]+)'?:\s*N_\((['"])(.*?)\2\)""", body, re.M)
    return {key: english.replace("\\'", "'") for key, _, english in rows}


def _locale_catalogue(locale: str):
    path = LOCALES_DIR / locale.replace("-", "_") / "LC_MESSAGES/ui.po"
    with path.open("rb") as handle:
        return read_po(handle, locale=locale.replace("-", "_"))


def test_every_setting_the_server_sends_has_a_label_and_so_does_its_section(tmp_path):
    keys = [entry.key for entry in describe_settings(Config(), path=tmp_path / "config.yaml")]
    labelled = _table("settingLabels.ts", "SETTINGS")
    sections = _table("settingLabels.ts", "SECTIONS")

    assert not [key for key in keys if key not in labelled], "settings without a label"
    assert not [key for key in keys if key.split(".", 1)[0] not in sections]
    assert not [key for key in labelled if key not in keys], "labels for settings that are gone"


def test_every_relationship_kind_the_server_can_send_has_a_label_and_a_statement():
    kinds = {choice.kind for choice in relationships.RELATIONSHIP_CHOICES}
    kinds |= set(relationships._RECIPROCAL) | set(relationships._RECIPROCAL.values())

    for table in ("LABELS", "STATEMENTS"):
        words = _table("people/relationshipLabels.ts", table)
        assert sorted(kinds - set(words)) == [], table
        assert sorted(set(words) - kinds) == [], table


def test_the_kinship_chain_reaches_the_client_as_kinds_not_english():
    suggestion = Suggestion(
        source="riley",
        kind="cousin-of",
        target="sky",
        reverse_kind="cousin-of",
        hops=(Hop("child", "bob"), Hop("sibling", "alex"), Hop("parent", "sky")),
    )
    names = {"riley": "Riley", "bob": "Bob", "alex": "Alex", "sky": "Sky"}

    steps = [(s.person, s.kind, s.other) for s in _chain_steps(suggestion, names)]

    assert steps == [
        ("Riley", "child-of", "Bob"),
        ("Bob", "sibling-of", "Alex"),
        ("Alex", "parent-of", "Sky"),
    ]
    assert {kind for _, kind, _ in steps} <= set(
        _table("people/relationshipLabels.ts", "STATEMENTS")
    )


def test_every_reason_the_scan_gives_for_a_link_has_a_word():
    emitted = set()
    for path in (Path(__file__).resolve().parents[1] / "src/immich_memories/people").glob("*.py"):
        emitted |= set(re.findall(r'via="([\w-]+)"', path.read_text()))
    emitted.add("you")

    assert emitted <= set(_table("people/relationshipLabels.ts", "VIA"))


def test_every_language_words_the_settings_and_relationships():
    english = [
        *_table("settingLabels.ts", "SETTINGS").values(),
        *_table("settingLabels.ts", "SECTIONS").values(),
        *_table("people/relationshipLabels.ts", "LABELS").values(),
        *_table("people/relationshipLabels.ts", "STATEMENTS").values(),
        *_table("people/relationshipLabels.ts", "VIA").values(),
    ]
    for locale in SUPPORTED_LOCALES:
        catalogue = _locale_catalogue(locale)
        for message in english:
            entry = catalogue.get(message)
            assert entry and entry.string, (locale, message)
            if locale != "en" and message.startswith("{a} is "):
                assert entry.string != message, (locale, message)
