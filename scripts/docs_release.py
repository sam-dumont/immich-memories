"""Choose the public documentation destination for a release."""

from __future__ import annotations

import json
import re
import sys


def final_for_candidate(version: str, tags: list[str]) -> str | None:
    """Return the final site to preserve, or publish this release at the root."""
    if not re.fullmatch(r"v?\d+\.\d+\.\d+-(?:rc|dev)\.\d+", version):
        return None
    finals = [tag for tag in tags if re.fullmatch(r"v?\d+\.\d+\.\d+", tag)]
    finals = [tag for tag in finals if int(tag.removeprefix("v").split(".")[0]) >= 1]
    if not finals:
        return None
    return max(finals, key=lambda tag: tuple(map(int, tag.removeprefix("v").split("."))))


def latest_published_release(pages: list[list[dict]]) -> str:
    """Choose the newest published app release, including release candidates."""
    releases = [
        release
        for page in pages
        for release in page
        if not release["draft"]
        and release.get("published_at")
        and re.fullmatch(r"v?\d+\.\d+\.\d+(?:-rc\.\d+)?", release["tag_name"])
    ]
    if not releases:
        raise ValueError("No published application release found.")
    return max(releases, key=lambda release: release["published_at"])["tag_name"]


if __name__ == "__main__":
    if sys.argv[1] == "--latest-published":
        try:
            print(latest_published_release(json.load(sys.stdin)))
        except ValueError as error:
            sys.exit(str(error))
    else:
        print(final_for_candidate(sys.argv[1], sys.stdin.read().splitlines()) or "")
