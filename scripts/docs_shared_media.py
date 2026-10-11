"""Let the /next/ and /dev/ docs trees use the stable tree's copy of large media.

Three full docs trees would carry three copies of the same demo videos. A track
built from a ref whose `docs-site/static/<path>` is the same git blob as the
stable ref's (same bytes; for LFS files, the same pointer) lists that path; the
site's media components then link the stable copy, and the assembly drops the
track's own. A file whose bytes differ is never listed, so the track keeps it.

Usage:
    python3 scripts/docs_shared_media.py select --stable-ref REF [--min-size BYTES]
    python3 scripts/docs_shared_media.py assemble --tracks JSON --trees DIR --site DIR --max-mb N
"""

from __future__ import annotations

import argparse
import filecmp
import json
import shutil
import subprocess
import sys
from pathlib import Path

STATIC = "docs-site/static/"
LIST = "shared-media.json"
SITE_BASE = "/immich-memories/"


def select_shared(
    own: dict[str, str], stable: dict[str, str], sizes: dict[str, int], min_size: int
) -> list[str]:
    """Static paths (relative to static/) whose blob matches stable and are at least min_size."""
    return sorted(
        path
        for path, blob in own.items()
        if stable.get(path) == blob and sizes.get(path, 0) >= min_size
    )


def _blobs(ref: str) -> dict[str, str]:
    listing = subprocess.check_output(["git", "ls-tree", "-r", ref, "--", STATIC], text=True)
    blobs = {}
    for line in listing.splitlines():
        meta, path = line.split("\t", 1)
        blobs[path.removeprefix(STATIC)] = meta.split()[2]
    return blobs


def _size(total: int) -> str:
    return f"{total / 1024 / 1024:.0f} MiB" if total >= 1024 * 1024 else f"{total // 1024} KiB"


def _tree_size(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def _share(tree: Path, stable: Path, base: str) -> None:
    listing = tree / LIST
    if not listing.exists():
        return  # built before shared media existed: keeps every file
    shared = json.loads(listing.read_text())
    listing.unlink()
    for name in shared:
        if not filecmp.cmp(tree / name, stable / name, shallow=False):
            raise ValueError(f"{base}{name} differs from the stable copy")
    # The media components link the stable copy. A page that still names the
    # track's own copy (a plain link, say) keeps it, so nothing 404s.
    pages = "\n".join(
        page.read_text(encoding="utf-8", errors="replace") for page in tree.rglob("*.html")
    )
    for name in shared:
        if f"{base}{name}" in pages:
            print(f"keeping {base}{name}: a page links it")
        else:
            (tree / name).unlink()


def assemble(tracks: list[dict], trees: Path, site: Path, max_bytes: int) -> dict[str, int]:
    """Place each track at its path, drop shared copies, and refuse an oversized site."""
    stable = trees / "docs-stable"
    sizes = {}
    for entry in tracks:
        tree = trees / f"docs-{entry['track']}"
        if entry["path"]:
            _share(tree, stable, f"{SITE_BASE}{entry['path']}/")
        sizes[entry["track"]] = _tree_size(tree)
        shutil.copytree(tree, site / entry["path"], dirs_exist_ok=True)
    total = _tree_size(site)
    for track, size in sizes.items():
        print(f"{track}: {_size(size)}")
    print(f"site: {_size(total)}")
    if total > max_bytes:
        raise ValueError(f"The assembled site is {_size(total)}, over the {_size(max_bytes)} limit")
    return sizes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    select = commands.add_parser("select")
    select.add_argument("--stable-ref", required=True)
    select.add_argument("--min-size", type=int, default=256 * 1024)
    place = commands.add_parser("assemble")
    place.add_argument("--tracks", required=True)
    place.add_argument("--trees", type=Path, required=True)
    place.add_argument("--site", type=Path, required=True)
    place.add_argument("--max-mb", type=int, required=True)
    args = parser.parse_args()
    if args.command == "select":
        own = _blobs("HEAD")
        sizes = {path: (Path(STATIC) / path).stat().st_size for path in own}
        print(json.dumps(select_shared(own, _blobs(args.stable_ref), sizes, args.min_size)))
        return 0
    try:
        assemble(json.loads(args.tracks), args.trees, args.site, args.max_mb * 1024 * 1024)
    except ValueError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
