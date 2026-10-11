import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from scripts.docs_release import plan_tracks


def _tracks(tags, dev=None):
    return {entry["track"]: entry["ref"] for entry in plan_tracks(tags, dev)}


def test_before_the_first_final_the_newest_candidate_is_stable():
    tags = ["v0.103.0", "v1.0.0-rc.8", "v1.0.0-rc.9"]
    assert _tracks(tags) == {"stable": "v1.0.0-rc.9"}


def test_a_candidate_newer_than_the_final_is_next():
    tags = ["v1.0.0-rc.9", "v1.0.0", "v1.1.0-rc.1", "v1.1.0-rc.2"]
    assert _tracks(tags) == {"stable": "v1.0.0", "next": "v1.1.0-rc.2"}


def test_a_candidate_older_than_the_final_is_not_shown():
    tags = ["v1.0.0-rc.9", "v1.0.0", "v1.0.1"]
    assert _tracks(tags) == {"stable": "v1.0.1"}


def test_the_newest_final_wins_by_version_not_by_listing_order():
    assert _tracks(["v1.10.0", "v1.2.0", "v1.11.0-rc.1"]) == {
        "stable": "v1.10.0",
        "next": "v1.11.0-rc.1",
    }


@pytest.mark.parametrize("nightly", [None, "c" * 40])
def test_dev_is_the_latest_nightly_when_there_is_one(nightly):
    tracks = plan_tracks(["v1.0.0", "v1.1.0-rc.1"], nightly)
    by_track = {entry["track"]: entry for entry in tracks}
    assert set(by_track) == ({"stable", "next", "dev"} if nightly else {"stable", "next"})
    assert by_track["stable"]["path"] == ""
    assert by_track["next"]["path"] == "next"
    if nightly:
        assert by_track["dev"] == {
            "track": "dev",
            "ref": nightly,
            "version": "",
            "path": "dev",
            "stable": "v1.0.0",
        }
    # Stable and next build from their release tags, with the tag as their version.
    assert by_track["next"]["version"] == "v1.1.0-rc.1"


def test_rehearsal_model_and_nightly_tags_are_never_a_docs_track():
    tags = ["v1.0.0-rc.9", "v0.0.0-dev.123", "models-v9", "nightly"]
    assert _tracks(tags) == {"stable": "v1.0.0-rc.9"}


def test_no_release_means_no_docs():
    with pytest.raises(ValueError, match="No published application release"):
        plan_tracks(["models-v9"], None)


@pytest.mark.parametrize("publish_final", [False, True])
def test_tracks_read_only_published_releases_across_pages(publish_final):
    pages = [
        [
            {"tag_name": "models-v9", "published_at": "2026-10-12T00:00:00Z", "draft": False},
            {"tag_name": "v1.0.0", "published_at": None, "draft": True},
            {"tag_name": "v0.0.0-dev.123", "published_at": "2026-10-11T00:00:00Z", "draft": False},
            {"tag_name": "v1.0.0-rc.8", "published_at": "2026-10-08T00:00:00Z", "draft": False},
        ],
        [
            {"tag_name": "v0.103.0", "published_at": "2026-09-01T00:00:00Z", "draft": False},
            {"tag_name": "v1.0.0-rc.9", "published_at": "2026-10-09T00:00:00Z", "draft": False},
        ],
    ]
    if publish_final:
        pages.append(
            [{"tag_name": "v1.0.0", "published_at": "2026-10-15T00:00:00Z", "draft": False}]
        )
    result = subprocess.run(
        [sys.executable, "scripts/docs_release.py", "--tracks", "--dev-ref", "d" * 40],
        input=json.dumps(pages),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    tracks = {entry["track"]: entry["ref"] for entry in json.loads(result.stdout)}
    assert tracks == {
        "stable": "v1.0.0" if publish_final else "v1.0.0-rc.9",
        "dev": "d" * 40,
    }


def test_tracks_refuse_to_publish_without_an_app_release():
    result = subprocess.run(
        [sys.executable, "scripts/docs_release.py", "--tracks", "--dev-ref", ""],
        input="[[]]",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.strip() == "No published application release found."


def _docs_step(job, name):
    workflow = yaml.safe_load(Path(".github/workflows/docs.yml").read_text())
    return next(step for step in workflow["jobs"][job]["steps"] if step.get("name") == name)


@pytest.mark.parametrize("nightly", [True, False])
def test_every_docs_deploy_plans_all_tracks_from_the_published_state(tmp_path, nightly):
    step = _docs_step("plan", "Choose what each track is built from")
    (tmp_path / "scripts").symlink_to(Path("scripts").resolve(), target_is_directory=True)
    (tmp_path / "releases.json").write_text(
        json.dumps(
            [
                [
                    {"tag_name": "v1.0.0", "draft": False, "published_at": "2026-10-20T00:00:00Z"},
                    {"tag_name": "v1.1.0-rc.1", "draft": False, "published_at": "2026-10-21Z"},
                    {"tag_name": "nightly", "draft": False, "published_at": "2026-10-22Z"},
                ]
            ]
        )
    )
    nightly_body = json.dumps({"body": f"Commit: {'c' * 40}"})
    # WHY: GitHub is the release catalogue; exercise the real shell and selectors.
    gh = tmp_path / "gh"
    gh.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = release ]; then\n'
        + (f"  printf '%s' '{nightly_body}'; exit 0\n" if nightly else "  exit 1\n")
        + "fi\n"
        'printf "%s\\n" "$*" > gh-arguments\ncat releases.json\n'
    )
    gh.chmod(0o700)
    output = tmp_path / "github-output"
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", step["run"]],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "GITHUB_OUTPUT": str(output),
            "GITHUB_REPOSITORY": "owner/project",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "gh-arguments").read_text().strip() == (
        "api --paginate --slurp repos/owner/project/releases?per_page=100"
    )
    key, _, value = output.read_text().strip().partition("=")
    assert key == "tracks"
    tracks = {entry["track"]: entry["ref"] for entry in json.loads(value)}
    expected = {"stable": "v1.0.0", "next": "v1.1.0-rc.1"}
    if nightly:
        expected["dev"] = "c" * 40
    assert tracks == expected


def test_the_site_puts_each_track_at_its_path(tmp_path):
    step = _docs_step("assemble", "Place each track at its path")
    tracks = plan_tracks(["v1.0.0", "v1.1.0-rc.1"], "c" * 40)
    for entry in tracks:
        tree = tmp_path / "tracks" / f"docs-{entry['track']}"
        tree.mkdir(parents=True)
        (tree / "index.html").write_text(entry["track"])
    subprocess.run(
        ["bash", "-c", step["run"]],
        env={**os.environ, "RUNNER_TEMP": str(tmp_path), "TRACKS": json.dumps(tracks)},
        check=True,
        capture_output=True,
    )
    site = tmp_path / "site"
    assert (site / "index.html").read_text() == "stable"
    assert (site / "next/index.html").read_text() == "next"
    assert (site / "dev/index.html").read_text() == "dev"


def test_each_track_builds_from_its_own_ref_at_its_own_base():
    workflow = yaml.safe_load(Path(".github/workflows/docs.yml").read_text())
    build = workflow["jobs"]["build"]
    assert build["strategy"]["matrix"]["include"] == "${{ fromJSON(needs.plan.outputs.tracks) }}"
    checkout = build["steps"][0]
    assert checkout["with"]["ref"] == "${{ matrix.ref }}"
    site = next(step for step in build["steps"] if step.get("name") == "Build site")
    assert site["env"]["DOCS_TRACK"] == "${{ matrix.track }}"
    # Release tags cut before DOCS_TRACK existed still read DOCS_NEXT.
    assert site["env"]["DOCS_NEXT"] == "${{ matrix.track == 'next' }}"
    assert workflow["jobs"]["deploy"]["needs"] == ["assemble"]


@pytest.mark.parametrize(
    ("env", "track", "path"),
    [
        ({}, "stable", ""),
        ({"DOCS_NEXT": "true"}, "next", "next/"),
        ({"DOCS_TRACK": "next"}, "next", "next/"),
        ({"DOCS_TRACK": "dev", "DOCS_NEXT": "false"}, "dev", "dev/"),
    ],
)
def test_a_docs_build_knows_its_track_and_base(env, track, path):
    module = json.dumps(str(Path("docs-site/scripts/docs-track.mjs").resolve()))
    script = (
        f"import {{docsTrack, trackPath}} from {module};"
        f"const t = docsTrack({json.dumps(env)}); console.log(t + ' ' + trackPath(t));"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split(" ") == [track, f"{path}\n"]


def test_an_unknown_docs_track_is_refused():
    module = json.dumps(str(Path("docs-site/scripts/docs-track.mjs").resolve()))
    script = f"import {{docsTrack}} from {module}; docsTrack({{DOCS_TRACK: 'beta'}});"
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=10
    )
    assert result.returncode != 0
    assert "Invalid DOCS_TRACK" in result.stderr
