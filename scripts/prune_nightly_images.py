"""List the GHCR package versions whose dated nightly tags have expired.

A version is deleted only when every tag it carries is `nightly-YYYYMMDD` (or its
`-cuda` twin) and the newest of those dates is at least `keep_days` old. Anything
also tagged `nightly`, a release version, `latest`, a commit build, or nothing at
all (the per-platform children of a multi-arch image) is never listed.

Usage:
    gh api --paginate --slurp /users/OWNER/packages/container/NAME/versions \
      | python3 scripts/prune_nightly_images.py [--today YYYYMMDD] [--keep-days 14]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime

_DATED = re.compile(r"nightly-(\d{8})(?:-cuda)?")


def expired_versions(versions: list[dict], today: str, keep_days: int = 14) -> list[int]:
    """Ids of the versions to delete."""
    now = datetime.strptime(today, "%Y%m%d").replace(tzinfo=UTC)
    expired = []
    for version in versions:
        tags = version.get("metadata", {}).get("container", {}).get("tags", [])
        dates = [_DATED.fullmatch(tag) for tag in tags]
        if not tags or not all(dates):
            continue
        newest = max(
            datetime.strptime(match[1], "%Y%m%d").replace(tzinfo=UTC) for match in dates if match
        )
        if (now - newest).days >= keep_days:
            expired.append(version["id"])
    return expired


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--today", default=datetime.now(UTC).strftime("%Y%m%d"))
    parser.add_argument("--keep-days", type=int, default=14)
    args = parser.parse_args()
    versions = [version for page in json.load(sys.stdin) for version in page]
    for version_id in expired_versions(versions, args.today, args.keep_days):
        print(version_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
