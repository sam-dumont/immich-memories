"""Fail when the web client uses or ships Immich's logos or store badges.

@immich/ui is MIT, but the Immich name and logos are trademarks outside that grant. Vite inlines
small SVGs into JavaScript, so a bundle scan alone misses them: the source imports are checked
first, the emitted asset files second.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "web" / "src"
BUNDLE = ROOT / "src" / "immich_memories" / "web" / "client"

# Every brand export of @immich/ui 0.90: the logos, the Logo component and the store badges.
BRAND_EXPORTS = re.compile(
    r"\b(immichLogo\w*|immichFuto\w*|Logo|appStoreBadge|fdroidBadge|playStoreBadge|obtainiumBadge)\b"
)
IMMICH_UI_IMPORT = re.compile(r"import\s*\{([^}]*)\}\s*from\s*['\"]@immich/ui['\"]", re.S)
# Components that draw the Immich logo unless told otherwise: a Modal without `icon=` does.
LOGO_BY_DEFAULT = re.compile(r"<Modal\b(?![^>]*\bicon=)[^>]*>", re.S)
BRAND_FILES = re.compile(
    r"(immich-logo|appstore-badge|fdroid-badge|playstore-badge|obtainium-badge)"
)


def main(argv: list[str] | None = None) -> int:
    """0 when no Immich brand asset is used or shipped.

    `--require-bundle` also fails when there is no built client to scan: the client is not
    committed (#1580), so a guard run before `make web-build` would otherwise pass on nothing.
    """
    require_bundle = "--require-bundle" in (sys.argv[1:] if argv is None else argv)
    if require_bundle and not (BUNDLE / "index.html").is_file():
        print(f"{BUNDLE} is not built: run make web-build before checking what it ships")
        return 1
    problems = [
        f"{path.relative_to(ROOT)} imports {name} from @immich/ui"
        for path in SOURCE.rglob("*")
        if path.suffix in {".svelte", ".ts", ".js"}
        for block in IMMICH_UI_IMPORT.findall(path.read_text())
        for name in BRAND_EXPORTS.findall(block)
    ]
    problems += [
        f"{path.relative_to(ROOT)} has a <Modal> without icon=, which draws the Immich logo"
        for path in SOURCE.rglob("*.svelte")
        if LOGO_BY_DEFAULT.search(path.read_text())
    ]
    problems += [
        f"{path.relative_to(ROOT)} is an Immich brand asset"
        for path in BUNDLE.rglob("*")
        if BRAND_FILES.search(path.name)
    ]
    for problem in problems:
        print(problem)
    if problems:
        print("Immich's logos and badges are trademarks, not part of @immich/ui's MIT grant.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
