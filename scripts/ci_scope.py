#!/usr/bin/env python3
"""Decide which CI jobs a pull request's changed files can break.

Every job used to run on every push: ~23 jobs for a one-line selection fix,
more than the 20 the account runs at once. The `changes` job runs this and
each job reads the scope in its `if:`. A job skipped that way reports as
passing, so the rollup checks stay green without it.

Only an area proven untouched is skipped. A path no rule knows, a build or
dependency file, an empty diff, or any event other than a pull request (a push
to main, the release and the nightly calling CI) runs everything.

It also answers the unit job's matrix (the Python/OS cells, each in shards) and, for a
pull request, the FFmpeg integration suites its diff coverage needs.

Usage:
    python3 scripts/ci_scope.py --event pull_request --base origin/main
    python3 scripts/ci_scope.py --event pull_request --integration-suites
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess  # nosec B404 - runs git with fixed arguments
import sys
from dataclasses import dataclass, fields
from fnmatch import fnmatch
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Scope:
    docs_only: bool  # nothing but prose: only the tests that read it run
    docs_site: bool  # the docs build
    store: bool  # the store suite and the PostgreSQL legs
    container: bool  # the Docker builds and container e2e
    python: bool  # Python code: the full Python/OS test matrix rather than one cell
    unit: bool  # the unit suite
    package: bool  # the wheel build
    launch: bool  # the hermetic launch check (Playwright e2e) and the fixture-library features
    immich: bool  # the real-Immich gate and the feature runs on real Immich
    render_worker: bool  # the render worker's own suite
    extras: bool  # the torch-family extras tests

    def as_outputs(self) -> dict[str, str]:
        return {item.name: str(getattr(self, item.name)).lower() for item in fields(self)}


DOCS_SITE = ("docs-site/*",)
DOCS = (*DOCS_SITE, "docs/*", "*.md", ".github/ISSUE_TEMPLATE/*")
STORE = (
    "src/immich_memories/store/*",
    "src/immich_memories/db/*",
    "tests/store/*",
    "alembic.ini",
    "scripts/with_throwaway_postgres.sh",
)
# The Dockerfile copies src/, packages/ and services/render-worker/; a src/
# change that needs a new dependency also changes pyproject.toml, which runs everything.
CONTAINER = (
    "docker/*",
    "docker-compose.yml",
    ".dockerignore",
    "deploy/*",
    "services/*",
    "packages/*",
    "tests/container/*",
)
# What the app is made of. Every suite that runs the app reads all of it: generous
# on purpose, since the launch check and the feature suites drive most of src/.
APP = ("src/*", "web/*", "packages/*")
PACKAGE = (*APP, "README.md", "LICENSE*", "THIRD_PARTY_NOTICES*")
LAUNCH = (
    *APP,
    "tests/e2e/*",
    "tests/features/*",
    "tests/integration/conftest.py",
    "tests/integration/features/*",
    "tests/immich_fakes.py",
    # How CI splits the e2e and feature suites into shards (`make e2e`, `make test-features`).
    "scripts/shard_tests.py",
    "tests/shard_durations.json",
)
IMMICH = (
    *LAUNCH,
    "tests/integration/immich_gate/*",
    "tests/integration/native_sharing/*",
    "scripts/immich_gate_images.sh",
    "scripts/with_throwaway_postgres.sh",
)
# The worker imports titles and processing, and through them the package's core.
# The modules at the top of src/immich_memories (config, preflight, generate, ...)
# feed every part of the app, so they count here and for the extras too.
RENDER_WORKER = (
    "services/render-worker/*",
    "src/immich_memories/processing/*",
    "src/immich_memories/titles/*",
    "src/immich_memories/photos/*",
    "src/immich_memories/api/*",
    "src/immich_memories/tracking/*",
    "src/immich_memories/locales/*",
    "packages/*",
)
# The test files marked `extras` (tests/test_ci_scope.py checks the list against
# the marker) and the parts of src/ they import.
EXTRAS_TESTS = (
    "tests/test_demucs_local.py",
    "tests/test_extras_marker_contract.py",
    "tests/test_local_reader.py",
    "tests/test_privacy_pipeline.py",
)
EXTRAS = (
    *EXTRAS_TESTS,
    "src/immich_memories/audio/*",
    "src/immich_memories/analysis/*",
    "src/immich_memories/processing/*",
    "src/immich_memories/cli/*",
)
TOP_OF_THE_PACKAGE = "src/immich_memories/"
# Code the unit suite covers, with no area of its own.
CODE = (
    "src/*",
    "tests/*",
    "scripts/*",
    "examples/*",
    "web/*",
    "complexity-watermark.json",
    "vulture-whitelist.py",
    "THIRD_PARTY_NOTICES*",
    ".pre-commit-config.yaml",
)
PYTHON = ("*.py", "src/*", "tests/*", "services/*", "packages/*", "scripts/*")
# Read by every job, so no area can be ruled out. Checked before CODE, which also matches them.
EVERY_JOB = (
    "pyproject.toml",
    "uv.lock",
    "Makefile",
    ".python-version",
    ".github/workflows/*",
    ".github/actions/*",
    "tests/conftest.py",
    "scripts/ci_scope.py",
)
# Suites whose tests read doc pages: a page one of them names runs it, docs-only or not.
SUITES_READING_DOCS = {
    "launch": ("tests/e2e", "tests/features", "tests/integration/features"),
    "immich": ("tests/features", "tests/integration/features", "tests/integration/immich_gate"),
}
EVERYTHING = Scope(**{item.name: item.name != "docs_only" for item in fields(Scope)})

# The unit suite's Python/OS cells. This repo is public, so hosted runners are free but
# capped, and macOS at 5 concurrent jobs: three macOS cells per pull request meant ~30
# jobs queueing for 5 slots once a handful of PRs were open, and GitHub reclaimed runs
# mid-job. A pull request keeps every Ubuntu Python and one macOS; main and the release
# run the full grid. A change with no Python in it (the web client, the image) runs one
# cell: the grid exists to catch code that behaves differently there.
ONE_CELL = (("ubuntu-24.04", "3.12"),)
PULL_REQUEST_CELLS = (
    ("ubuntu-24.04", "3.11"),
    ("ubuntu-24.04", "3.12"),
    ("ubuntu-24.04", "3.13"),
    ("macos-latest", "3.13"),
)
ALL_CELLS = (
    *PULL_REQUEST_CELLS[:3],
    ("macos-latest", "3.11"),
    ("macos-latest", "3.12"),
    PULL_REQUEST_CELLS[3],
)
# The cell whose shards record coverage for the combined floor, diff-cover and Codecov.
COVERAGE_CELL = ("ubuntu-24.04", "3.12")
# Each cell runs the suite in this many jobs (`make test-cov-xml TEST_SHARD=i/N`), but see
# unit_shards: macOS outside a pull request.
UNIT_SHARDS = 2


def unit_shards(os_name: str, event: str) -> int:
    """How many jobs a cell's suite runs in: macOS cells stay whole outside a pull request.

    Main and the release run three macOS cells; in shards that would be six jobs against
    the 5-job macOS cap, so there each runs whole (~14 min) in one slot of its own.
    """
    return 1 if os_name.startswith("macos") and event != "pull_request" else UNIT_SHARDS


# The FFmpeg-only integration suites (`make test-integration-<suite>`) that reach a changed
# source path. A pull request runs them before diff-cover, so code only FFmpeg reaches
# reads as covered; their coverage XMLs are gitignored and never come from a contributor.
INTEGRATION_SUITES = (
    ("src/immich_memories/titles/", ("titles",)),
    ("src/immich_memories/processing/", ("processing", "assembly")),
    ("src/immich_memories/photos/", ("photos",)),
    ("src/immich_memories/audio/", ("audio-mixing",)),
    ("src/immich_memories/generate", ("assembly",)),
    ("src/immich_memories/processing/remote_render", ("render-worker",)),
    ("services/render-worker/", ("render-worker",)),
)


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch(path, pattern) for pattern in patterns)


def _top_of_the_package(path: str) -> bool:
    return path.startswith(TOP_OF_THE_PACKAGE) and "/" not in path.removeprefix(TOP_OF_THE_PACKAGE)


def _runs_everything(path: str) -> bool:
    if _matches(path, EVERY_JOB):
        return True
    known = (*DOCS, *STORE, *CONTAINER, *CODE, *IMMICH, *RENDER_WORKER)
    return not _matches(path, known)


def _is_docs(path: str) -> bool:
    # A prompt under src/ or a README under deploy/ is Markdown the code or the
    # image reads, so the code areas win over the `*.md` pattern.
    return _matches(path, DOCS) and not _matches(path, (*STORE, *CONTAINER, *CODE))


def _named_by(path: str, suites: tuple[str, ...], repo: Path) -> bool:
    """Whether a file in these test suites names the page, by path or file name."""
    name = path.rpartition("/")[2]
    return any(
        path in text or name in text
        for suite in suites
        for test in sorted((repo / suite).rglob("*.py"))
        if (text := test.read_text(encoding="utf-8", errors="replace"))
    )


def scope(paths: list[str], *, event: str, repo: Path = REPO) -> Scope:
    """Scope the jobs to the areas the changed paths belong to."""
    if event != "pull_request" or not paths or any(_runs_everything(path) for path in paths):
        return EVERYTHING
    docs = [path for path in paths if _is_docs(path)]
    read = {
        job: any(_named_by(path, suites, repo) for path in docs)
        for job, suites in SUITES_READING_DOCS.items()
    }
    docs_only = len(docs) == len(paths)

    def touched(patterns: tuple[str, ...], *, with_top: bool = False) -> bool:
        return any(_matches(p, patterns) or (with_top and _top_of_the_package(p)) for p in paths)

    return Scope(
        docs_only=docs_only,
        docs_site=touched(DOCS_SITE),
        store=touched(STORE),
        container=touched(CONTAINER),
        python=touched(PYTHON),
        unit=not docs_only,
        package=touched(PACKAGE),
        launch=touched(LAUNCH) or read["launch"],
        immich=touched(IMMICH) or read["immich"],
        render_worker=touched(RENDER_WORKER, with_top=True),
        extras=touched(EXTRAS, with_top=True),
    )


def unit_matrix(scope: Scope, event: str) -> dict[str, list[dict[str, object]]]:
    """The unit job's matrix: every cell the scope runs, each in its shards."""
    if not scope.python:
        cells = ONE_CELL
    elif event == "pull_request":
        cells = PULL_REQUEST_CELLS
    else:
        cells = ALL_CELLS
    return {
        "include": [
            {
                "os": os_name,
                "python-version": python,
                "shard": shard,
                "shards": unit_shards(os_name, event),
                "coverage": (os_name, python) == COVERAGE_CELL,
            }
            for os_name, python in cells
            for shard in range(1, unit_shards(os_name, event) + 1)
        ]
    }


def integration_suites(paths: list[str]) -> list[str]:
    """The integration suites whose FFmpeg paths these changed Python files are on."""
    changed = [
        path
        for path in paths
        if path.endswith(".py")
        and path.startswith(("src/immich_memories/", "services/render-worker/"))
    ]
    return sorted(
        {
            suite
            for prefix, suites in INTEGRATION_SUITES
            for path in changed
            if path.startswith(prefix)
            for suite in suites
        }
    )


def outputs(paths: list[str], *, event: str, repo: Path = REPO) -> dict[str, str]:
    """Every output of the `changes` job: the scope, the unit matrix and the integration suites."""
    found = scope(paths, event=event, repo=repo)
    # Only a pull request has a diff to cover; main and the release check the floor alone.
    suites = integration_suites(paths) if event == "pull_request" and found.unit else []
    return {
        **found.as_outputs(),
        "unit_matrix": json.dumps(unit_matrix(found, event), separators=(",", ":")),
        "integration_suites": json.dumps(suites, separators=(",", ":")),
    }


def _changed_paths(base: str) -> list[str]:
    diff = subprocess.run(  # nosec B603 B607 - fixed git invocation
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in diff.stdout.splitlines() if line]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--event", required=True)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument(
        "--integration-suites",
        action="store_true",
        help="print the integration suites the diff against --base reaches, and nothing else",
    )
    args = parser.parse_args()

    if args.integration_suites:
        print(" ".join(integration_suites(_changed_paths(args.base))))
        return 0
    paths = _changed_paths(args.base) if args.event == "pull_request" else []
    lines = [f"{name}={value}" for name, value in outputs(paths, event=args.event).items()]
    print("\n".join(lines))
    if github_output := os.environ.get("GITHUB_OUTPUT"):
        with open(github_output, "a", encoding="utf-8") as sink:
            sink.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
