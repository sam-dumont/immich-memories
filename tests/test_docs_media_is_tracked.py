"""Every picture and film a docs page points at is a tracked file of the site.

The docs build doesn't check a `<Video src>` or a poster, and `*.mp4` is ignored outside the
listed demo folders: a film written to a new folder looked fine on disk, passed the build, and
went live as a 404. The index is what CI checks out, so the test reads it, not the disk.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = "docs-site/static"
# A quoted or linked path under /demo/ or /img/ with a file extension: `src="/demo/x.mp4"`,
# `poster='/img/x.jpg'`, `useMediaUrl('/demo/x.mp4')`, `](/img/x.png)`.
_REFERENCE = re.compile(r"""["'`(](/(?:demo|img)/[^"'`)\s#?$]+\.[a-z0-9]{2,4})["'`)]""")


def _tracked_static_files() -> set[str]:
    listed = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", STATIC],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    return {path.removeprefix(STATIC) for path in listed}


def _references() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    pages = [p for part in ("docs", "src") for p in (ROOT / "docs-site" / part).glob("**/*")]
    for page in sorted(pages):
        # Pages and the components that render them; a test's own sample paths are not links.
        if (
            page.suffix not in {".md", ".mdx", ".tsx", ".ts", ".js", ".json"}
            or ".test." in page.name
        ):
            continue
        for path in _REFERENCE.findall(page.read_text(encoding="utf-8")):
            found.setdefault(path, set()).add(str(page.relative_to(ROOT)))
    return found


def test_every_docs_media_reference_is_a_tracked_file():
    tracked = _tracked_static_files()

    missing = {path: pages for path, pages in _references().items() if path not in tracked}

    assert not missing, missing


def test_the_reference_pattern_reads_videos_posters_and_markdown_images():
    page = (
        '<Video src="/demo/tiers/month.mp4" poster="/demo/tiers/month-contact.jpg" />\n'
        "![A frame](/img/trip-map-flyover.jpg)\n"
        '<StaticFile href="/demo/tiers/provenance.json">provenance</StaticFile>'
    )

    assert _REFERENCE.findall(page) == [
        "/demo/tiers/month.mp4",
        "/demo/tiers/month-contact.jpg",
        "/img/trip-map-flyover.jpg",
        "/demo/tiers/provenance.json",
    ]
