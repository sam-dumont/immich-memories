"""Decide whether tonight's build of `main` has anything to publish, and under what name.

The marker for "the last nightly" is the commit named in the body of the rolling
`nightly` GitHub prerelease. The body is written last, by the step that publishes
the release, so a run that failed half-way leaves the old marker and the next run
builds again.

Usage (from the nightly workflow):
    python3 scripts/nightly.py plan [--date YYYYMMDD]   # writes GITHUB_OUTPUT
    python3 scripts/nightly.py last-commit             # prints the marker, or nothing
    python3 scripts/nightly.py notes VERSION COMMIT TAG
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from fnmatch import fnmatch
from pathlib import Path

try:  # run as a script, `scripts/` is on the path; imported by tests, it is a package
    from release_analyze import sort_version_tags
except ModuleNotFoundError:
    from scripts.release_analyze import sort_version_tags

RELEASE = "nightly"
INFERENCE_DOCKERFILE = "docker/Dockerfile.inference"
_MARKER = re.compile(r"(?m)^Commit: ([0-9a-f]{40})\s*$")
_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-rc\.(\d+))?$")


@dataclass(frozen=True)
class NightlyPlan:
    """What tonight's run builds, and why."""

    build: bool
    inference: bool
    reason: str


def last_nightly_commit(body: str | None) -> str | None:
    """The commit the published nightly was built from, if its release says so."""
    match = _MARKER.search(body or "")
    return match[1] if match else None


def nightly_version(tags: list[str], day: str) -> str:
    """A PEP 440 dev version that sorts after the last release and before the next.

    After a final X.Y.Z it is X.Y.(Z+1).devDAY; after a candidate X.Y.Z-rc.N it is
    X.Y.ZrcN+1.devDAY. No local `+g<sha>` part: GitHub renames release assets that
    contain `+`, which would break the wheel's file name. The notes name the commit.
    """
    ordered = sort_version_tags(tags)
    if not ordered:
        return f"0.0.1.dev{day}"
    match = _TAG.match(ordered[0])
    assert match is not None  # sort_version_tags keeps only matching tags
    major, minor, patch, candidate = match.groups()
    if candidate:
        return f"{major}.{minor}.{patch}rc{int(candidate) + 1}.dev{day}"
    return f"{major}.{minor}.{int(patch) + 1}.dev{day}"


def inference_sources(dockerfile: str) -> list[str]:
    """The repository paths the inference image is built from, read from its COPY lines."""
    sources = [INFERENCE_DOCKERFILE, ".dockerignore"]
    for line in dockerfile.splitlines():
        words = line.split()
        if not words or words[0].upper() not in {"COPY", "ADD"}:
            continue
        flags = [word for word in words[1:] if word.startswith("--")]
        if any(flag.startswith("--from") for flag in flags):
            continue
        paths = [word for word in words[1:] if not word.startswith("--")]
        sources.extend(path.removeprefix("./") for path in paths[:-1])
    return sources


def inference_changed(changed: list[str], sources: list[str]) -> bool:
    """True when any changed path is, or sits under, something the image copies in."""

    def matches(path: str, source: str) -> bool:
        if source.endswith("/"):
            return path.startswith(source)
        if any(char in source for char in "*?["):
            return fnmatch(path, source)
        return path == source or path.startswith(f"{source}/")

    return any(matches(path, source) for path in changed for source in sources)


def plan(
    *, head: str, previous: str | None, changed: list[str], sources: list[str], force: bool
) -> NightlyPlan:
    """Build when main moved since the last nightly, or when asked to."""
    if previous is None:
        return NightlyPlan(True, True, "No published nightly yet: building everything.")
    inference = inference_changed(changed, sources)
    if previous != head:
        return NightlyPlan(True, inference, f"main moved since the nightly of {previous[:12]}.")
    if force:
        return NightlyPlan(True, False, "Nothing new on main; building anyway on request.")
    return NightlyPlan(False, False, f"Nothing new on main since {head[:12]}; nothing to publish.")


def nightly_notes(version: str, commit: str, tag: str) -> str:
    """The release body. Its `Commit:` line is the marker the next run compares against."""
    image = "ghcr.io/sam-dumont/immich-memories"
    return (
        f"Nightly build of `main`, version `{version}`. For testing what is on `main`; "
        "not for production. Replaced by the next nightly.\n\n"
        f"- App image: `{image}:{tag}` (also `:nightly`)\n"
        f"- Inference images: `{image}/inference:{tag}` and `{tag}-cuda`\n"
        "- Wheel and Compose files: attached below. Not published to PyPI.\n\n"
        f"Commit: {commit}\n"
    )


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def _published_body() -> str | None:
    result = subprocess.run(
        ["gh", "release", "view", RELEASE, "--json", "body"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return json.loads(result.stdout).get("body")


def _known(commit: str) -> bool:
    return (
        subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"], capture_output=True, check=False
        ).returncode
        == 0
    )


def _write_outputs(outputs: dict[str, str]) -> None:
    destination = os.environ.get("GITHUB_OUTPUT")
    lines = "".join(f"{key}={value}\n" for key, value in outputs.items())
    if destination:
        with open(destination, "a", encoding="utf-8") as stream:
            stream.write(lines)
    else:
        print(lines, end="")


def _plan_command(day: str) -> int:
    head = os.environ["GITHUB_SHA"]
    previous = last_nightly_commit(_published_body())
    # A marker the checkout cannot see (a rewritten history) counts as no marker.
    if previous is not None and not _known(previous):
        previous = None
    changed = _git("diff", "--name-only", previous, head).splitlines() if previous else []
    sources = inference_sources(Path(INFERENCE_DOCKERFILE).read_text(encoding="utf-8"))
    decision = plan(
        head=head,
        previous=previous,
        changed=changed,
        sources=sources,
        force=os.environ.get("FORCE") == "true",
    )
    print(decision.reason, file=sys.stderr)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write(f"## Nightly\n\n{decision.reason}\n")
    _write_outputs(
        {
            "build": str(decision.build).lower(),
            "inference": str(decision.inference).lower(),
            "version": nightly_version(_git("tag", "--list", "v*").splitlines(), day),
            "tag": f"nightly-{day}",
            "previous": previous or "",
        }
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan_parser = commands.add_parser("plan")
    plan_parser.add_argument("--date", default=datetime.now(UTC).strftime("%Y%m%d"))
    commands.add_parser("last-commit")
    notes = commands.add_parser("notes")
    notes.add_argument("version")
    notes.add_argument("commit")
    notes.add_argument("tag")
    args = parser.parse_args()
    if args.command == "plan":
        return _plan_command(args.date)
    if args.command == "last-commit":
        print(last_nightly_commit(_published_body()) or "")
        return 0
    print(nightly_notes(args.version, args.commit, args.tag), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
