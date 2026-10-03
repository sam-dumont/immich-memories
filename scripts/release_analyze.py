"""Decide what a release run should publish, and say so in GITHUB_OUTPUT terms.

Extracted from the release workflow so the decision has tests. The invariant
this guards (#1010): a tag whose GitHub Release never got created — an
interrupted publication — must be resumed with the same version on the next
run, not become the baseline that advances the version or, with no commits
after it, concludes there is nothing to release. "Tag exists" is not evidence
that a release completed.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass

_VERSION_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-rc\.(\d+))?$")

# Anything that changes what ships. A final must not carry one of these unless a
# candidate did; docs, tests, ci, chore and style do not reach the artifacts.
_UNTESTED_CHANGE = re.compile(
    r"^((feat|fix|perf|refactor|build|revert)(\(.+\))?!?:|[a-z]+(\(.+\))?!:|BREAKING[ -]CHANGE:)",
    re.MULTILINE,
)


@dataclass(frozen=True)
class Decision:
    """What the workflow should do: release, resume, or stand down."""

    should_release: bool
    next_version: str = ""
    release_type: str = "none"
    resumed: bool = False
    previous_tag: str = ""
    prerelease: bool = False
    note: str = ""


def _version_key(tag: str) -> tuple[int, int, int, int, int]:
    match = _VERSION_TAG.match(tag)
    if match is None:
        raise ValueError(f"not a version tag: {tag}")
    major, minor, patch, candidate = match.groups()
    # A final sorts above every candidate of its version: (…, 1, 0) > (…, 0, n).
    return (int(major), int(minor), int(patch), 0 if candidate else 1, int(candidate or 0))


def sort_version_tags(tags: list[str]) -> list[str]:
    """Version tags newest first, release candidates below their final.

    Git's own version sort ranks v1.0.0-rc.1 above v1.0.0, which would make a
    candidate look newer than the release it led to.
    """
    return sorted((tag for tag in tags if _VERSION_TAG.match(tag)), key=_version_key, reverse=True)


def _is_candidate(tag: str) -> bool:
    return "-rc." in tag


def _core(tag: str) -> str:
    return tag.removeprefix("v").split("-", 1)[0]


def _bump(previous: str, release_type: str) -> str:
    major, minor, patch = (int(part) for part in previous.split("."))
    if release_type == "major":
        return f"{major + 1}.0.0"
    if release_type == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def _series_type(stable: str | None, core: str) -> str:
    """The bump a candidate series makes over the last final, for approval gating."""
    old = [int(part) for part in (_core(stable) if stable else "0.0.0").split(".")]
    new = [int(part) for part in core.split(".")]
    if new[0] != old[0]:
        return "major"
    return "minor" if new[1] != old[1] else "patch"


def _type_from_branches(merged_branches: str) -> str:
    if re.search(r"(breaking/|major/)", merged_branches, re.IGNORECASE):
        return "major"
    if re.search(r"(feat/|feature/|minor/)", merged_branches, re.IGNORECASE):
        return "minor"
    if re.search(r"(fix/|bugfix/|patch/|hotfix/)", merged_branches, re.IGNORECASE):
        return "patch"
    return "none"


def _type_from_commits(commit_bodies: str) -> str:
    if re.search(r"^[a-z]+(\(.+\))?!:|^BREAKING[ -]CHANGE:", commit_bodies, re.MULTILINE):
        return "major"
    if re.search(r"^feat(\(.+\))?:", commit_bodies, re.MULTILINE):
        return "minor"
    if re.search(r"^(fix|perf)(\(.+\))?:", commit_bodies, re.MULTILINE):
        return "patch"
    return "none"


def published_baseline(tags: list[str], release_exists) -> str | None:
    """The newest tag whose GitHub Release was actually created."""
    return next((tag for tag in tags if release_exists(tag)), None)


def decide(
    *,
    tags: list[str],
    release_exists,
    merged_branches: str,
    commit_bodies: str,
    force_version: str | None = None,
    channel: str = "stable",
    commits_since_latest: str | None = None,
) -> Decision:
    """Choose between a new version, a release candidate, and resuming one.

    Args:
        tags: every version tag, in any order.
        release_exists: callable answering whether a GitHub Release was created
            for a tag; the difference between a published version and a
            stranded one.
        merged_branches: merge-commit subjects since the last published final.
        commit_bodies: full commit messages since the last published final.
        force_version: manual bump override for a fresh release or a new series.
        channel: "stable" for a final, "rc" for a release candidate. While a
            candidate series is open, "stable" promotes it and "rc" continues it.
        commits_since_latest: commit messages since the newest published tag,
            candidate or final; defaults to commit_bodies.
    """
    version_tags = sort_version_tags(tags)
    baseline = published_baseline(version_tags, release_exists)

    # An interrupted publication left a tag with no release behind it. Publish
    # that exact version again regardless of what the commits since the
    # baseline would bump to: the stranded tag was already chosen, and the
    # images or manifests that reference it may already exist.
    if version_tags and version_tags[0] != baseline:
        release_type = _release_type(baseline, merged_branches, commit_bodies) or "patch"
        return Decision(
            should_release=True,
            next_version=version_tags[0].removeprefix("v"),
            release_type=release_type,
            resumed=True,
            previous_tag=baseline or "",
            prerelease=_is_candidate(version_tags[0]),
        )

    stable = published_baseline(
        [tag for tag in version_tags if not _is_candidate(tag)], release_exists
    )
    since_latest = commit_bodies if commits_since_latest is None else commits_since_latest
    if baseline and _is_candidate(baseline):
        return _continue_series(baseline, stable, channel, since_latest)

    release_type = _release_type(baseline, merged_branches, commit_bodies)
    if force_version and force_version != "auto":
        release_type = force_version
    if release_type == "none":
        return Decision(should_release=False)
    core = _bump(_core(stable) if stable else "0.0.0", release_type)
    candidate = channel == "rc"
    return Decision(
        should_release=True,
        next_version=f"{core}-rc.1" if candidate else core,
        release_type=release_type,
        previous_tag=stable or "",
        prerelease=candidate,
    )


def _continue_series(open_candidate: str, stable: str | None, channel: str, since: str) -> Decision:
    """Cut the next candidate of an open series, or promote the last one to final."""
    core = _core(open_candidate)
    release_type = _series_type(stable, core)
    following = f"{core}-rc.{_version_key(open_candidate)[4] + 1}"
    if channel == "rc":
        if not since.strip():
            return Decision(should_release=False, note=f"nothing new since {open_candidate}")
        return Decision(
            should_release=True,
            next_version=following,
            release_type=release_type,
            previous_tag=open_candidate,
            prerelease=True,
        )
    if _UNTESTED_CHANGE.search(since):
        return Decision(
            should_release=False,
            note=f"changes since {open_candidate} were in no candidate; cut {following} first",
        )
    return Decision(
        should_release=True,
        next_version=core,
        release_type=release_type,
        previous_tag=stable or "",
    )


def _release_type(baseline: str | None, merged_branches: str, commit_bodies: str) -> str:
    release_type = _type_from_branches(merged_branches)
    if release_type == "none":
        release_type = _type_from_commits(commit_bodies)
    return release_type


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True)


def _release_exists(tag: str, repo: str) -> bool:
    command = ["gh", "release", "view", tag, "--json", "tagName"]
    if repo:
        command += ["--repo", repo]
    try:
        result = subprocess.run(command, capture_output=True, text=True)
    except FileNotFoundError as error:
        raise RuntimeError(
            "the gh CLI is required to tell a published release from a tag"
        ) from error
    return result.returncode == 0


def _since(tag: str | None) -> list[str]:
    return [f"{tag}..HEAD"] if tag else []


def format_outputs(decision: Decision) -> dict[str, str]:
    """The GITHUB_OUTPUT lines the workflow's steps read."""
    outputs = {"should_release": str(decision.should_release).lower()}
    if decision.should_release:
        outputs["next_version"] = decision.next_version
        outputs["release_type"] = decision.release_type
        outputs["prerelease"] = str(decision.prerelease).lower()
        outputs["previous_tag"] = decision.previous_tag
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force-version", default=None)
    parser.add_argument("--channel", choices=("stable", "rc", "dev"), default="stable")
    images = parser.add_mutually_exclusive_group()
    images.add_argument("--inference-only", action="store_true")
    images.add_argument("--app-only", action="store_true")
    args = parser.parse_args()

    if args.channel == "dev":
        run_id = os.environ.get("GITHUB_RUN_ID", "")
        if not run_id.isdecimal() or int(run_id) < 1:
            parser.error("dev rehearsal requires a positive GITHUB_RUN_ID")
        if args.inference_only or args.app_only:
            parser.error("dev rehearsal publishes the complete artifact set; omit image-only flags")
        if os.environ.get("GITHUB_RUN_ATTEMPT", "1") != "1":
            parser.error(
                "dispatch a new dev rehearsal; reruns must not replace candidate artifacts"
            )
        decision = Decision(
            should_release=True,
            next_version=f"0.0.0-dev.{run_id}",
            release_type="development",
            prerelease=True,
        )
        for key, value in format_outputs(decision).items():
            print(f"{key}={value}")
        return 0

    if args.inference_only or args.app_only:
        sha = os.environ.get("GITHUB_SHA", "")
        for key, value in {
            "should_release": "false",
            "next_version": f"0+g{sha}",
        }.items():
            print(f"{key}={value}")
        return 0

    repo = os.environ.get("GITHUB_REPOSITORY", "")
    try:
        _git("fetch", "--tags", "--force")
    except (subprocess.CalledProcessError, OSError):
        # A fresh or remote-less checkout still has its local tags to reason about.
        pass
    tags = sort_version_tags(_git("tag", "--list", "v*").splitlines())

    def released(tag: str) -> bool:
        return _release_exists(tag, repo)

    # Type and evidence come from the commits since the published final; a
    # stranded tag on HEAD must not shrink that range to nothing, and neither
    # may a candidate, which has not shipped as a final yet.
    stable = published_baseline([tag for tag in tags if not _is_candidate(tag)], released)
    latest = published_baseline(tags, released)
    merged_branches = _git("log", *_since(stable), "--merges", "--pretty=format:%s")
    commit_bodies = _git("log", *_since(stable), "--pretty=format:%B")
    commits_since_latest = _git("log", *_since(latest), "--pretty=format:%B")

    decision = decide(
        tags=tags,
        release_exists=released,
        merged_branches=merged_branches,
        commit_bodies=commit_bodies,
        force_version=args.force_version,
        channel=args.channel,
        commits_since_latest=commits_since_latest,
    )

    if decision.resumed:
        # stderr: the workflow appends stdout to GITHUB_OUTPUT, which takes key=value lines only.
        print(
            f"Resuming interrupted release: tag v{decision.next_version} has no GitHub Release",
            file=sys.stderr,
        )
    if decision.note:
        # A deliberate dispatch that cannot do what it was asked should fail visibly.
        print(f"::error::No release: {decision.note}", file=sys.stderr)
        return 1
    outputs = format_outputs(decision)
    destination = os.environ.get("GITHUB_OUTPUT")
    if destination:
        with open(destination, "a", encoding="utf-8") as stream:
            for key, value in outputs.items():
                stream.write(f"{key}={value}\n")
    else:
        for key, value in outputs.items():
            print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
