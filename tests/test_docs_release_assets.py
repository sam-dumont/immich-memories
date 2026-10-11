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


def _clean_env():
    """The pre-commit hook exports GIT_DIR and GIT_INDEX_FILE; keep them off the scratch repo."""
    import os

    return {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}


def _gate_repo(tmp_path):
    """A clone where v0.103.0 shipped one setup file fewer than main lists now."""
    import shutil

    repo = tmp_path / "repo"
    shutil.copytree("scripts", repo / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run([*git, "init", "-q"], check=True, env=_clean_env())
    subprocess.run([*git, "add", "-A"], check=True, env=_clean_env())
    subprocess.run([*git, "commit", "-q", "-m", "v0.103.0"], check=True, env=_clean_env())
    subprocess.run([*git, "tag", "v0.103.0"], check=True, env=_clean_env())
    compose = repo / "scripts" / "package_compose.py"
    compose.write_text(
        compose.read_text().replace(
            "COMPOSE_ASSETS = (", 'COMPOSE_ASSETS = (\n    "added-later.xml",', 1
        )
    )
    return repo


def _run_gate(repo, tracks, release):
    import os

    import yaml

    workflow = yaml.safe_load(Path(".github/workflows/docs.yml").read_text())
    gate = next(
        step
        for step in workflow["jobs"]["plan"]["steps"]
        if step.get("name") == "Verify matching setup release assets"
    )
    # The gate runs in `plan`, before any track is built.
    assert workflow["jobs"]["build"]["needs"] == ["plan"]
    (repo / "release.json").write_text(json.dumps(release))
    gh = repo / "gh"
    gh.write_text("#!/bin/sh\nprintf '%s\\n' \"$3\" >> checked\ncat release.json\n")
    gh.chmod(0o700)
    return subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", gate["run"]],
        cwd=repo,
        env={**_clean_env(), "PATH": f"{repo}:{os.environ['PATH']}", "TRACKS": json.dumps(tracks)},
        capture_output=True,
        text=True,
        check=False,
    )


DEV = {"track": "dev", "ref": "c" * 40, "version": "", "path": "dev"}
STABLE = {"track": "stable", "ref": "v0.103.0", "version": "v0.103.0", "path": ""}


def test_docs_workflow_checks_versioned_assets_but_leaves_dev_docs_offline(tmp_path):
    repo = _gate_repo(tmp_path)
    empty = {"tagName": "v0.103.0", "assets": []}
    assert _run_gate(repo, [DEV], empty).returncode == 0
    assert _run_gate(repo, [STABLE, DEV], empty).returncode == 1
    # Only the versioned track was looked up; dev docs link no release assets.
    assert (repo / "checked").read_text().split() == ["v0.103.0"]


def test_a_release_is_checked_against_the_setup_files_its_own_tag_ships(tmp_path):
    from scripts.package_compose import COMPOSE_ASSETS

    repo = _gate_repo(tmp_path)
    shipped = [
        *COMPOSE_ASSETS,
        "immich-memories-deploy-0.103.0.tar.gz",
        "SHA256SUMS",
        "installation.json",
    ]
    release = {
        "tagName": "v0.103.0",
        "assets": [{"name": name, "state": "uploaded", "size": 100} for name in shipped],
    }
    # main now lists added-later.xml; the tag never shipped it, and its docs never link it.
    result = _run_gate(repo, [STABLE], release)
    assert result.returncode == 0, result.stderr
    release["assets"] = release["assets"][1:]
    result = _run_gate(repo, [STABLE], release)
    assert result.returncode == 1
    assert COMPOSE_ASSETS[0] in result.stderr


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
