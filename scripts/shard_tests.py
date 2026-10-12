#!/usr/bin/env python3
"""Split a suite's test files into CI shards of about equal running time.

The unit, e2e and feature suites each took longer on one runner than CI should take
in all. CI runs each as N jobs; each calls the suite's make target with TEST_SHARD,
E2E_SHARD or FEATURE_SHARD set to i/N, and the target runs the files this script picks
for shard i. Whole files, because a module's fixtures run once for all its tests.

The split is the longest-first greedy one over the seconds each file took in that suite
(tests/shard_durations.json, recorded from JUnit reports); a file with no record counts
as an average one. It depends only on the file names and the record, so every job
computes the same split and each file lands in exactly one shard.

Usage:
    python3 scripts/shard_tests.py pick features 2/3 tests/integration/features/test_*.py
    python3 scripts/shard_tests.py pick unit "" FILES...      # no shard: every file
    python3 scripts/shard_tests.py record e2e tests/e2e-junit.xml
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree  # nosec B405 - reads JUnit reports pytest wrote here

REPO = Path(__file__).resolve().parents[1]
DURATIONS = REPO / "tests" / "shard_durations.json"
SHARD = re.compile(r"(\d+)/(\d+)")


def pick(files: list[str], index: int, count: int, durations: dict[str, float]) -> list[str]:
    """The files of shard `index` of `count` (1-based), sorted by name."""
    unique = sorted(set(files))
    known = [durations[f] for f in unique if f in durations]
    average = sum(known) / len(known) if known else 1.0
    weight = {f: durations.get(f, average) for f in unique}
    loads = [0.0] * count
    shards: list[list[str]] = [[] for _ in range(count)]
    for path in sorted(unique, key=lambda f: (-weight[f], f)):
        lightest = loads.index(min(loads))
        loads[lightest] += weight[path]
        shards[lightest].append(path)
    return sorted(shards[index - 1])


def _file_of(classname: str, root: Path) -> str | None:
    """The test file a JUnit classname (`tests.e2e.test_x` or `tests.e2e.test_x.TestY`) is in."""
    parts = classname.split(".")
    for end in range(len(parts), 0, -1):
        path = "/".join(parts[:end]) + ".py"
        if (root / path).is_file():
            return path
    return None


def record(
    suite: str, reports: list[Path], durations: Path = DURATIONS, *, root: Path = REPO
) -> None:
    """Replace the suite's recorded seconds of every file these JUnit reports ran."""
    seconds: dict[str, float] = defaultdict(float)
    for report in reports:
        for case in ElementTree.parse(report).iter("testcase"):  # noqa: S314  # nosec B314
            if path := _file_of(case.get("classname", ""), root):
                seconds[path] += float(case.get("time", 0))
    recorded = json.loads(durations.read_text()) if durations.exists() else {}
    section = recorded.get(suite, {})
    section.update({path: round(total, 1) for path, total in seconds.items()})
    recorded[suite] = dict(sorted(section.items()))
    durations.write_text(json.dumps(dict(sorted(recorded.items())), indent=2) + "\n")


def _pick_command(suite: str, spec: str, files: list[str]) -> int:
    if not spec:
        print("\n".join(sorted(set(files))))
        return 0
    match = SHARD.fullmatch(spec)
    if not match or not 1 <= int(match.group(1)) <= int(match.group(2)):
        print(f"shard {spec!r}: expected i/N with 1 <= i <= N", file=sys.stderr)
        return 2
    recorded = json.loads(DURATIONS.read_text()) if DURATIONS.exists() else {}
    picked = pick(files, int(match.group(1)), int(match.group(2)), recorded.get(suite, {}))
    if not picked:
        # pytest given no path runs the whole default suite: an empty shard is an error.
        print(f"shard {spec}: no file left for it among {len(set(files))}", file=sys.stderr)
        return 1
    print("\n".join(picked))
    return 0


def main(argv: list[str]) -> int:
    match argv:
        case ["pick", suite, spec, *files]:
            return _pick_command(suite, spec, files)
        case ["record", suite, *reports]:
            record(suite, [Path(report) for report in reports])
            return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
