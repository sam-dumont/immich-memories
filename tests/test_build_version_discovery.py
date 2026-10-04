"""Model releases must not rename the app or hide a docs build's identity."""

import json
import os
import re
import shlex
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_git_environment(monkeypatch):
    # Commit hooks export GIT_DIR/GIT_INDEX_FILE; temporary repos must not inherit them.
    for key in list(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key)


@pytest.fixture
def tagged_repo(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()

    git("init", "-q")
    git("config", "user.name", "Version test")
    git("config", "user.email", "version@example.test")
    git("commit", "--allow-empty", "-qm", "release")
    git("tag", "v1.2.3")
    git("commit", "--allow-empty", "-qm", "models")
    git("tag", "models-v99")
    return tmp_path, git


def docs_version(root, version=None):
    script = (
        f"import {{resolveDocsVersion}} from {json.dumps(str(ROOT / 'docs-site/build-version.ts'))};"
        f"console.log(resolveDocsVersion({json.dumps({'DOCS_VERSION': version} if version else {})}, {json.dumps(str(root))}));"
    )
    return subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_docs_main_build_names_the_release_and_commit_even_after_a_model_tag(tagged_repo):
    root, git = tagged_repo
    result = docs_version(root)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"v1.2.3-1-g{git('rev-parse', '--short=12', 'HEAD')}"


@pytest.mark.parametrize("version", ["v1.2.3", "v1.3.0-rc.2", "v0.0.0-dev.12345"])
def test_docs_explicit_release_version_is_not_replaced_by_the_checkout(tagged_repo, version):
    result = docs_version(tagged_repo[0], version)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == version


def test_docs_do_not_accept_model_tags_or_html_as_a_release_version(tagged_repo):
    for version in ("models-v99", "<img src=x onerror=alert(1)>"):
        assert docs_version(tagged_repo[0], version).returncode != 0


def test_docs_build_on_an_exact_release_uses_that_tag(tagged_repo):
    root, git = tagged_repo
    git("tag", "v1.3.0-rc.2")
    assert docs_version(root).stdout.strip() == "v1.3.0-rc.2"


def test_python_version_discovery_ignores_model_tags_and_retains_commit_identity(tagged_repo):
    root, git = tagged_repo
    options = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["hatch"]["version"][
        "raw-options"
    ]
    description = subprocess.check_output(
        shlex.split(options["scm"]["git"]["describe_command"]),
        cwd=root,
        text=True,
        env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
    ).strip()
    assert description.startswith("v1.2.3-1-g")
    assert options["local_scheme"] == "node-and-date"
    assert re.fullmatch(options["tag_regex"], "v1.3.0-rc.2").group("version") == "1.3.0-rc.2"
    assert (
        re.fullmatch(options["tag_regex"], "v0.0.0-dev.12345").group("version") == "0.0.0-dev.12345"
    )
    assert not re.fullmatch(options["tag_regex"], "models-v99")


def test_python_version_discovery_after_a_rehearsal_skips_the_rehearsal_tag(tagged_repo):
    # setuptools-scm cannot bump a custom `.devN` number, so a commit after a
    # `v0.0.0-dev.RUN` rehearsal tag would make every later build fail (#1974).
    root, git = tagged_repo
    git("tag", "v0.0.0-dev.12345")
    git("commit", "--allow-empty", "-qm", "after the rehearsal")
    options = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["hatch"]["version"][
        "raw-options"
    ]
    description = subprocess.check_output(
        shlex.split(options["scm"]["git"]["describe_command"]), cwd=root, text=True
    ).strip()
    assert description.startswith("v1.2.3-2-g")
