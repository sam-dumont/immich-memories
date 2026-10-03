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

    for version in ("1.2.3", "1.2.4-rc.1", "0.0.0-dev.12345"):
        names = [
            *COMPOSE_ASSETS,
            f"immich-memories-deploy-{version}.tar.gz",
            "SHA256SUMS",
            "installation.json",
        ]
        if "-dev." in version:
            names.append(f"immich_memories-{version.replace('-dev.', '.dev')}-py3-none-any.whl")
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


def test_docs_workflow_checks_versioned_assets_but_leaves_previews_offline(tmp_path):
    import os

    import yaml

    workflow = yaml.safe_load(Path(".github/workflows/docs.yml").read_text())
    steps = workflow["jobs"]["build"]["steps"]
    gate = next(
        step for step in steps if step.get("name") == "Verify matching setup release assets"
    )
    assert steps.index(gate) < next(
        i for i, step in enumerate(steps) if step.get("name") == "Build site"
    )
    gh = tmp_path / "gh"
    gh.write_text('#!/bin/sh\nprintf \'{"tagName":"v0.103.0","assets":[]}\'\n')
    gh.chmod(0o700)
    for version, expected in [("v0.103.0", 1), ("development", 0), ("v0.103.0-4-gabc123", 0)]:
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", gate["run"]],
            env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "DOCS_VERSION": version},
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == expected, result.stderr


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
