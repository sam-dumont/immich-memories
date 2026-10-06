"""Refresh icons.json: the glyphs the figures use, cut from the Iconify JSON sets.

The figures name icons as 'mdi:chip' (Material Design Icons, Apache-2.0) or 'si:docker'
(Simple Icons, CC0-1.0). Only the ones in use are kept, so the build needs no npm install.

    npm i --no-save @iconify-json/mdi @iconify-json/simple-icons   (in docs-site/)
    python docs-site/diagrams/vendor_icons.py docs-site/node_modules/@iconify-json
"""

import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).parent
PACKS = {"mdi": "mdi", "si": "simple-icons"}


def main(iconify: pathlib.Path) -> None:
    used = sorted(
        {
            m
            for f in (HERE / "figures").glob("*.py")
            for m in re.findall(r'icon\("([a-z]+:[a-z0-9-]+)"', f.read_text())
        }
    )
    sets = {p: json.loads((iconify / pack / "icons.json").read_text()) for p, pack in PACKS.items()}
    icons = {}
    for spec in used:
        prefix, name = spec.split(":", 1)
        data = sets[prefix]
        entry = data["icons"][name]
        icons[spec] = {
            "body": entry["body"],
            "width": entry.get("width", data.get("width", 24)),
            "height": entry.get("height", data.get("height", 24)),
        }
    doc = {
        "source": "Iconify JSON sets",
        "licences": {"mdi": "Apache-2.0", "si": "CC0-1.0"},
        "icons": icons,
    }
    (HERE / "icons.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    print(f"icons.json: {len(icons)} icons")


if __name__ == "__main__":
    main(pathlib.Path(sys.argv[1]))
