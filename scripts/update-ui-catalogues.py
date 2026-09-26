"""Extract interface labels and update the shipped UI catalogues without guessing translations."""

import re
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path

from babel.messages.catalog import Catalog
from babel.messages.extract import extract_from_dir
from babel.messages.pofile import read_po, write_po

from immich_memories.i18n import LOCALES_DIR, SUPPORTED_LOCALES

UI_ROOT = Path(__file__).resolve().parents[1] / "src/immich_memories/ui"
WEB_ROOT = Path(__file__).resolve().parents[1] / "web/src"
# The Svelte client marks labels as t('...') or N_('...'); only literal first arguments count.
_WEB_LABEL = re.compile(r"""\b(?:t|N_)\(\s*(['"])((?:\\.|(?!\1).)+)\1""")


def _web_labels() -> Iterator[tuple[str, int, str]]:
    for path in sorted(WEB_ROOT.rglob("*")):
        if path.suffix not in {".svelte", ".ts"} or path.name == "api-types.ts":
            continue
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            for match in _WEB_LABEL.finditer(line):
                yield (
                    f"web/{path.relative_to(WEB_ROOT)}",
                    number,
                    match.group(2).replace("\\'", "'"),
                )


def main() -> None:
    """Keep existing drafts, add new labels, and record where each label is rendered."""
    template = Catalog(project="Immich Memories UI", charset="utf-8")
    for filename, line, message, comments, _ in extract_from_dir(
        str(UI_ROOT), keywords={"tr": (1,), "N_": (1,)}
    ):
        template.add(message, locations=[(filename, line)], auto_comments=comments)
    for filename, line, message in _web_labels():
        template.add(message, locations=[(filename, line)])
    for code in SUPPORTED_LOCALES:
        path = LOCALES_DIR / code.replace("-", "_") / "LC_MESSAGES/ui.po"
        if path.exists():
            with path.open("rb") as handle:
                catalogue = read_po(handle, locale=code.replace("-", "_"))
            catalogue.update(deepcopy(template), no_fuzzy_matching=True)
        else:
            catalogue = Catalog(locale=code.replace("-", "_"), project="Immich Memories UI")
            catalogue.update(deepcopy(template))
        catalogue.fuzzy = False
        provenance = (
            "English source." if code == "en" else "AI-drafted; native-speaker review welcome."
        )
        catalogue.header_comment = f"# Immich Memories interface translations.\n# {provenance}"
        if code == "en":
            for entry in catalogue:
                if entry.id:
                    entry.string = entry.id
        with path.open("wb") as handle:
            write_po(handle, catalogue, sort_output=True, width=96)


if __name__ == "__main__":
    main()
