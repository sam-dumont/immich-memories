"""Write a release's notes in the Immich format: highlights by hand, then the changes by group.

The highlights (an upgrade warning, a welcome line, a list of highlights and one short
section each) are written by a person, in the docs' voice, and kept in a Markdown file.
This script adds the part a person shouldn't type: every commit since the previous tag,
grouped under the emoji headings Immich uses, each with a link to its pull request, and the
full-changelog link. See docs-site/docs/contribute/releasing.md, "Release notes".

    uv run python scripts/release_notes.py v1.0.0-rc.10 v1.0.0 --highlights notes.md > out.md
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPOSITORY = "sam-dumont/immich-memories"

# In the order they appear. A commit lands in the first group whose rule matches.
GROUPS = (
    "🔒 Security",
    "🚀 Features",
    "⚡ Performance",
    "🐛 Bug fixes",
    "📚 Documentation",
    "🧹 Cleanup",
    "📦 Dependencies",
    "🔧 Build, CI and tests",
)

_SUBJECT = re.compile(r"^(\w+)(?:\(([^)]*)\))?(!)?: (.*?)(?: \(#(\d+)\))?$")
_SECURITY_SCOPES = {"security", "auth"}
_TOOLING_SCOPES = {"ci", "tests", "build", "release", "docs"}


def group_of(kind: str, scope: str) -> str:
    """The heading a commit of this conventional type and scope goes under."""
    scopes = set(scope.split(",")) if scope else set()
    if kind == "fix" and scopes & _SECURITY_SCOPES:
        return "🔒 Security"
    if kind == "feat":
        return "🚀 Features"
    if kind == "perf":
        return "⚡ Performance"
    if kind == "fix" and "deps" in scopes:
        return "🔒 Security"
    if kind == "build" and "deps" in scopes:
        return "📦 Dependencies"
    if kind == "docs" or (kind == "fix" and scopes == {"docs"}):
        return "📚 Documentation"
    if kind == "fix" and not scopes & _TOOLING_SCOPES:
        return "🐛 Bug fixes"
    if kind == "refactor":
        return "🧹 Cleanup"
    return "🔧 Build, CI and tests"


def changes(subjects: list[str], previous: str, current: str) -> str:
    """The "What's Changed" section for these commit subjects, newest first."""
    grouped: dict[str, list[str]] = {name: [] for name in GROUPS}
    for subject in subjects:
        match = _SUBJECT.match(subject.strip())
        if match is None:
            continue
        kind, scope, breaking, description, pull = match.groups()
        line = f"* {'**Breaking:** ' if breaking else ''}{description}"
        if pull:
            line += f" in https://github.com/{REPOSITORY}/pull/{pull}"
        grouped[group_of(kind, scope or "")].append(line)
    out = ["## What's Changed", ""]
    for name, lines in grouped.items():
        if lines:
            out += [f"### {name}", *lines, ""]
    out.append(
        f"**Full Changelog**: https://github.com/{REPOSITORY}/compare/{previous}...{current}"
    )
    return "\n".join(out) + "\n"


def subjects_between(previous: str, current: str) -> list[str]:
    """Commit subjects after `previous` up to `current` (a tag, or HEAD before tagging)."""
    result = subprocess.run(  # noqa: S603, S607 - fixed argv, no shell
        ["git", "log", "--format=%s", f"{previous}..{current}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("previous", help="the tag the notes start after, e.g. v1.0.0-rc.10")
    parser.add_argument("current", help="the tag being released, e.g. v1.0.0")
    parser.add_argument("--ref", default="HEAD", help="commit to read up to (default: HEAD)")
    parser.add_argument("--highlights", type=Path, help="hand-written part, printed first")
    args = parser.parse_args(argv)
    head = args.highlights.read_text().rstrip() + "\n\n" if args.highlights else ""
    sys.stdout.write(
        head + changes(subjects_between(args.previous, args.ref), args.previous, args.current)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
