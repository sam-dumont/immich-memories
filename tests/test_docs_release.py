import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from scripts.docs_release import final_for_candidate


def test_first_one_point_zero_candidates_publish_at_root():
    assert final_for_candidate("v1.0.0-rc.1", ["v0.103.0", "v1.0.0-rc.1"]) is None


def test_later_candidates_preserve_the_latest_final():
    assert final_for_candidate("v1.11.0-rc.1", ["v1.2.0", "v1.10.0", "v1.11.0-rc.1"]) == "v1.10.0"


def test_final_releases_publish_at_root():
    assert final_for_candidate("v1.1.0", ["v1.0.0"]) is None


@pytest.mark.parametrize("publish_final", [False, True])
def test_manual_docs_use_the_newest_published_app_release_across_pages(publish_final):
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
        [sys.executable, "scripts/docs_release.py", "--latest-published"],
        input=json.dumps(pages),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ("v1.0.0" if publish_final else "v1.0.0-rc.9")


def test_manual_docs_refuse_to_publish_without_an_app_release():
    result = subprocess.run(
        [sys.executable, "scripts/docs_release.py", "--latest-published"],
        input="[[]]",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.strip() == "No published application release found."


@pytest.mark.parametrize(
    ("event", "explicit", "tag", "expected"),
    [
        ("workflow_dispatch", "", "", "v1.0.0-rc.9"),
        ("release", "", "v1.0.0-rc.8", "v1.0.0-rc.8"),
        ("workflow_call", "v1.0.0-rc.7", "", "v1.0.0-rc.7"),
    ],
)
def test_workflow_resolves_download_version_without_changing_docs_source(
    tmp_path, event, explicit, tag, expected
):
    workflow = yaml.safe_load(Path(".github/workflows/docs.yml").read_text())
    steps = workflow["jobs"]["build"]["steps"]
    version_step = next(
        step for step in steps if step.get("name") == "Inject version from release tag"
    )
    checkout = steps[0]["with"]["ref"]
    assert checkout == "${{ inputs.version || github.event.release.tag_name || github.ref }}"
    (tmp_path / "scripts").symlink_to(Path("scripts").resolve(), target_is_directory=True)
    (tmp_path / "docs-site").mkdir()
    (tmp_path / "releases.json").write_text(
        json.dumps(
            [[{"tag_name": "v1.0.0-rc.9", "draft": False, "published_at": "2026-10-09T00:00:00Z"}]]
        )
    )
    # WHY: GitHub is the external release catalogue; exercise the real shell and selector.
    gh = tmp_path / "gh"
    gh.write_text('#!/bin/sh\nprintf "%s\\n" "$*" > gh-arguments\ncat releases.json\n')
    gh.chmod(0o700)
    # WHY: package.json stamping is existing Node behavior; no Node installation is needed here.
    node = tmp_path / "node"
    node.write_text('#!/bin/sh\necho "development-abcdef123456"\n')
    node.chmod(0o700)
    env_file = tmp_path / "github-env"
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", version_step["run"]],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "INPUT_VERSION": explicit,
            "RELEASE_TAG": tag,
            "EVENT_NAME": event,
            "GITHUB_ENV": str(env_file),
            "GITHUB_REPOSITORY": "owner/project",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert env_file.read_text() == f"DOCS_VERSION={expected}\n"
    if event == "workflow_dispatch":
        assert (tmp_path / "gh-arguments").read_text().strip() == (
            "api --paginate --slurp repos/owner/project/releases?per_page=100"
        )
    else:
        assert not (tmp_path / "gh-arguments").exists()
