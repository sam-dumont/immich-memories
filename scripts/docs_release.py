"""Choose the public documentation destination for a release."""

from __future__ import annotations

import re
import sys


def final_for_candidate(version: str, tags: list[str]) -> str | None:
    """Return the final site to preserve, or publish this release at the root."""
    if not re.fullmatch(r"v?\d+\.\d+\.\d+-rc\.\d+", version):
        return None
    finals = [tag for tag in tags if re.fullmatch(r"v?\d+\.\d+\.\d+", tag)]
    finals = [tag for tag in finals if int(tag.removeprefix("v").split(".")[0]) >= 1]
    if not finals:
        return None
    return max(finals, key=lambda tag: tuple(map(int, tag.removeprefix("v").split("."))))


if __name__ == "__main__":
    print(final_for_candidate(sys.argv[1], sys.stdin.read().splitlines()) or "")
