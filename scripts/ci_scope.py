#!/usr/bin/env python3
"""Decide which CI jobs a pull request's changed files can break.

Every job used to run on every push: ~23 jobs for a one-line selection fix,
more than the 20 the account runs at once. The `changes` job runs this and
each job reads the scope in its `if:`. A job skipped that way reports as
passing, so the rollup checks stay green without it.

Only an area proven untouched is skipped. A path no rule knows, a build or
dependency file, an empty diff, or any event other than a pull request (the
release calls CI through workflow_call) runs everything.

Usage:
    python3 scripts/ci_scope.py --event pull_request --base origin/main
"""

from __future__ import annotations

import argparse
import os
import subprocess  # nosec B404 - runs git with fixed arguments
import sys
from dataclasses import dataclass
from fnmatch import fnmatch


@dataclass(frozen=True)
class Scope:
    docs_only: bool
    docs_site: bool
    store: bool
    container: bool

    def as_outputs(self) -> dict[str, str]:
        return {name: str(value).lower() for name, value in vars(self).items()}


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
# Code the unit suite, launch check and Immich gate cover, with no area of its own.
CODE = (
    "src/*",
    "tests/*",
    "scripts/*",
    "examples/*",
    "complexity-watermark.json",
    "vulture-whitelist.py",
    "THIRD_PARTY_NOTICES*",
)
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
EVERYTHING = Scope(docs_only=False, docs_site=True, store=True, container=True)


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch(path, pattern) for pattern in patterns)


def _runs_everything(path: str) -> bool:
    if _matches(path, EVERY_JOB):
        return True
    known = (*DOCS, *STORE, *CONTAINER, *CODE)
    return not _matches(path, known)


def _is_docs(path: str) -> bool:
    # A prompt under src/ or a README under deploy/ is Markdown the code or the
    # image reads, so the code areas win over the `*.md` pattern.
    return _matches(path, DOCS) and not _matches(path, (*STORE, *CONTAINER, *CODE))


def scope(paths: list[str], *, event: str) -> Scope:
    """Scope the jobs to the areas the changed paths belong to."""
    if event != "pull_request" or not paths or any(_runs_everything(path) for path in paths):
        return EVERYTHING
    return Scope(
        docs_only=all(_is_docs(path) for path in paths),
        docs_site=any(_matches(path, DOCS_SITE) for path in paths),
        store=any(_matches(path, STORE) for path in paths),
        container=any(_matches(path, CONTAINER) for path in paths),
    )


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
    args = parser.parse_args()

    paths = _changed_paths(args.base) if args.event == "pull_request" else []
    outputs = scope(paths, event=args.event).as_outputs()
    lines = [f"{name}={value}" for name, value in outputs.items()]
    print("\n".join(lines))
    if github_output := os.environ.get("GITHUB_OUTPUT"):
        with open(github_output, "a", encoding="utf-8") as sink:
            sink.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
