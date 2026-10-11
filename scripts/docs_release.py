"""Choose which ref each public docs track is built from.

GitHub Pages serves one artifact, so every deploy builds all of them together:

- stable, at the root: the newest final release. Before the first final 1.x
  exists, the newest release of any kind (a candidate included) stays here.
- next, at /next/: the newest release candidate, only when it is newer than stable.
- dev, at /dev/: the commit the latest nightly was built from, when there is one.

Usage:
    gh api --paginate --slurp repos/OWNER/REPO/releases \
      | python3 scripts/docs_release.py --tracks --dev-ref SHA
"""

from __future__ import annotations

import argparse
import json
import re
import sys

try:  # run as a script, `scripts/` is on the path; imported by tests, it is a package
    from release_analyze import sort_version_tags
except ModuleNotFoundError:
    from scripts.release_analyze import sort_version_tags

_FINAL = re.compile(r"v\d+\.\d+\.\d+")


def _is_one_point_x_final(tag: str) -> bool:
    return bool(_FINAL.fullmatch(tag)) and int(tag[1:].split(".")[0]) >= 1


def plan_tracks(tags: list[str], dev_ref: str | None) -> list[dict[str, str]]:
    """One entry per track to build: its name, ref, version label and path under the site."""
    ordered = sort_version_tags(tags)
    if not ordered:
        raise ValueError("No published application release found.")
    finals = [tag for tag in ordered if _is_one_point_x_final(tag)]
    stable = finals[0] if finals else ordered[0]
    entry = {"stable": stable}  # every track compares its media with the stable ref
    tracks = [{"track": "stable", "ref": stable, "version": stable, "path": "", **entry}]
    # sort_version_tags ranks a final above its own candidates, so anything listed
    # before stable is newer than it; with no 1.x final yet, stable is the newest.
    newer = ordered[: ordered.index(stable)]
    candidate = next((tag for tag in newer if "-rc." in tag), None)
    if candidate:
        tracks.append(
            {"track": "next", "ref": candidate, "version": candidate, "path": "next", **entry}
        )
    if dev_ref:
        # Built from a commit, not a tag: the docs name it from `git describe`.
        tracks.append({"track": "dev", "ref": dev_ref, "version": "", "path": "dev", **entry})
    return tracks


def published_tags(pages: list[list[dict]]) -> list[str]:
    """Tags of every published (not draft) release across the API's pages."""
    return [
        release["tag_name"]
        for page in pages
        for release in page
        if not release["draft"] and release.get("published_at")
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracks", action="store_true", required=True)
    parser.add_argument("--dev-ref", default="")
    args = parser.parse_args()
    try:
        tracks = plan_tracks(published_tags(json.load(sys.stdin)), args.dev_ref or None)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    print(json.dumps(tracks, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
