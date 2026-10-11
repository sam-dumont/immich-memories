"""A versioned setup guide cannot publish links to absent release artifacts."""

import json
import subprocess
import sys
from pathlib import Path


def test_old_release_missing_compose_assets_is_refused():
    result = subprocess.run(
        [sys.executable, "scripts/check_docs_release_assets.py", "v0.103.0"],
        input=json.dumps(
            {"tagName": "v0.103.0", "assets": [{"name": "immich-memories-deploy-0.103.0.tar.gz"}]}
        ),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "docker-compose.yml" in result.stderr
    assert "example.env" in result.stderr


def test_complete_stable_and_candidate_release_assets_are_accepted():
    from scripts.package_compose import COMPOSE_ASSETS

    for version in ("1.2.3", "1.2.4-rc.1"):
        names = [
            *COMPOSE_ASSETS,
            f"immich-memories-deploy-{version}.tar.gz",
            "SHA256SUMS",
            "installation.json",
        ]
        result = subprocess.run(
            [sys.executable, "scripts/check_docs_release_assets.py", f"v{version}"],
            input=json.dumps(
                {
                    "tagName": f"v{version}",
                    "assets": [{"name": name, "state": "uploaded", "size": 100} for name in names],
                }
            ),
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr


def test_docs_workflow_checks_versioned_assets_but_leaves_dev_docs_offline(tmp_path):
    import os

    import yaml

    workflow = yaml.safe_load(Path(".github/workflows/docs.yml").read_text())
    steps = workflow["jobs"]["plan"]["steps"]
    gate = next(
        step for step in steps if step.get("name") == "Verify matching setup release assets"
    )
    # The gate runs in `plan`, before any track is built.
    assert workflow["jobs"]["build"]["needs"] == ["plan"]
    (tmp_path / "scripts").symlink_to(Path("scripts").resolve(), target_is_directory=True)
    gh = tmp_path / "gh"
    gh.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$3" >> checked\nprintf \'{"tagName":"v0.103.0","assets":[]}\'\n'
    )
    gh.chmod(0o700)
    dev = {"track": "dev", "ref": "c" * 40, "version": "", "path": "dev"}
    stable = {"track": "stable", "ref": "v0.103.0", "version": "v0.103.0", "path": ""}
    for tracks, expected in [([dev], 0), ([stable, dev], 1)]:
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", gate["run"]],
            cwd=tmp_path,
            env={
                **os.environ,
                "PATH": f"{tmp_path}:{os.environ['PATH']}",
                "TRACKS": json.dumps(tracks),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == expected, result.stderr
    # Only the versioned track was looked up; dev docs link no release assets.
    assert (tmp_path / "checked").read_text().split() == ["v0.103.0"]


def test_named_assets_must_have_finished_nonempty_uploads():
    from scripts.package_compose import COMPOSE_ASSETS

    names = [*COMPOSE_ASSETS, "immich-memories-deploy-1.2.3.tar.gz"]
    for state, size in [("uploading", 100), ("starter", 100), ("uploaded", 0)]:
        assets = [{"name": name, "state": "uploaded", "size": 100} for name in names]
        assets[0].update(state=state, size=size)
        result = subprocess.run(
            [sys.executable, "scripts/check_docs_release_assets.py", "v1.2.3"],
            input=json.dumps({"tagName": "v1.2.3", "assets": assets}),
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1
        assert "docker-compose.yml" in result.stderr


def test_rc_docs_require_the_checksum_and_identity_used_by_the_install_guide():
    from scripts.package_compose import COMPOSE_ASSETS

    names = [*COMPOSE_ASSETS, "immich-memories-deploy-1.0.0-rc.1.tar.gz"]
    result = subprocess.run(
        [sys.executable, "scripts/check_docs_release_assets.py", "v1.0.0-rc.1"],
        input=json.dumps(
            {
                "tagName": "v1.0.0-rc.1",
                "assets": [{"name": name, "state": "uploaded", "size": 100} for name in names],
            }
        ),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "SHA256SUMS" in result.stderr
    assert "installation.json" in result.stderr
