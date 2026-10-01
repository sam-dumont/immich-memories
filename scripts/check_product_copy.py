"""Check public descriptions against the shared product copy, without network access."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    """Refuse mismatched taglines in the package, app and release surfaces."""
    tagline = json.loads((ROOT / "docs-site/product.json").read_text())["tagline"]
    surfaces = (
        "README.md",
        "pyproject.toml",
        "docker/Dockerfile",
        "src/immich_memories/cli/__init__.py",
        "web/src/routes/login/+page.svelte",
        "docs-site/remotion/src/scenes/TitleScene.tsx",
    )
    missing = [name for name in surfaces if tagline not in (ROOT / name).read_text()]
    for catalogue in sorted((ROOT / "src/immich_memories/locales").glob("*/LC_MESSAGES/ui.po")):
        if f'msgid "{tagline}"' not in catalogue.read_text():
            missing.append(str(catalogue.relative_to(ROOT)))
    if missing:
        print("Product tagline differs from docs-site/product.json: " + ", ".join(missing))
        return 1
    print("Public product copy is consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
