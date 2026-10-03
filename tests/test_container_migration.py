"""The namespace migration copies pinned images without replacing newer releases."""

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/migrate-container-images.yml"


@pytest.mark.parametrize("mode", ["missing", "same", "conflict", "denied", "bad-copy"])
def test_migration_checks_existing_tags_and_copied_digest(tmp_path, mode):
    job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["migrate"]
    step = next(s for s in job["steps"] if s.get("name") == "Copy and verify pinned manifests")
    docker = tmp_path / "docker"
    docker.write_text("""#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
state = pathlib.Path(os.environ['RUNNER_TEMP']) / 'copied'
mode = os.environ['MODE']
digest = os.environ['DIGEST']
if args[2] == 'create':
    assert args[-1] == os.environ['SOURCE'] + '@' + digest
    state.write_text(json.dumps(args))
    sys.exit(0)
ref = args[3]
if ref.startswith(os.environ['TARGET']):
    if not state.exists() and mode == 'missing':
        print('manifest unknown: not found', file=sys.stderr)
        sys.exit(1)
    if mode == 'denied':
        print('unauthorized', file=sys.stderr)
        sys.exit(1)
    if (mode == 'conflict' and ref.endswith(':latest')) or (mode == 'bad-copy' and state.exists()):
        digest = 'sha256:' + 'b' * 64
print(json.dumps({'digest': digest}))
""")
    docker.chmod(0o755)
    env = {
        **os.environ,
        "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
        "SOURCE": "ghcr.io/sam-dumont/old",
        "TARGET": "ghcr.io/sam-dumont/new",
        "VERSION": "0.103.0",
        "ALIAS": "latest",
        "DIGEST": "sha256:" + "a" * 64,
        "MODE": mode,
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
    }
    result = subprocess.run(
        ["bash", "-c", step["run"]], env=env, capture_output=True, text=True, timeout=10
    )
    assert (result.returncode == 0) == (mode in {"missing", "same"}), result.stderr
    copied = tmp_path / "copied"
    assert copied.exists() == (mode not in {"conflict", "denied"})
    if result.returncode == 0:
        args = json.loads(copied.read_text())
        assert env["TARGET"] + ":0.103.0" in args
        assert env["TARGET"] + ":latest" in args
        assert (tmp_path / "summary").read_text().count(env["DIGEST"]) == 2


def test_shipped_kubernetes_pins_exist_in_the_migration():
    root = WORKFLOW.parents[2]
    entries = yaml.safe_load(WORKFLOW.read_text())["jobs"]["migrate"]["strategy"]["matrix"][
        "include"
    ]
    copied = {
        ("ghcr.io/sam-dumont/immich-memories" + entry["suffix"], entry["version"])
        for entry in entries
    }
    for path in (root / "deploy/kubernetes").rglob("kustomization.yaml"):
        for image in yaml.safe_load(path.read_text()).get("images", []):
            if image["name"].startswith("ghcr.io/sam-dumont/immich-memories"):
                assert (image["name"], image["newTag"]) in copied, path
