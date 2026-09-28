"""A pull request runs the jobs its changed files can break, and a file nobody classified runs them all."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ci_scope.py"


@pytest.fixture(scope="module")
def ci_scope():
    spec = importlib.util.spec_from_file_location("ci_scope", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module  # dataclasses resolve the owning module by name
    spec.loader.exec_module(module)
    return module


def test_a_selection_change_runs_the_code_jobs_on_sqlite_only(ci_scope):
    scope = ci_scope.scope(
        [
            "src/immich_memories/analysis/editorial_story_slots.py",
            "tests/test_editorial_story_slots.py",
        ],
        event="pull_request",
    )

    assert scope.as_outputs() == {
        "docs_only": "false",
        "docs_site": "false",
        "store": "false",
        "container": "false",
    }


def test_a_docs_page_change_builds_the_site_and_nothing_heavy(ci_scope):
    scope = ci_scope.scope(
        ["docs-site/docs/how-it-chooses/selection.md", "ARCHITECTURE.md"],
        event="pull_request",
    )

    assert scope.as_outputs() == {
        "docs_only": "true",
        "docs_site": "true",
        "store": "false",
        "container": "false",
    }


def test_markdown_the_app_reads_is_code_not_docs(ci_scope):
    scope = ci_scope.scope(["src/immich_memories/prompts/episode_reading.md"], event="pull_request")

    assert scope.docs_only is False


@pytest.mark.parametrize(
    "path",
    [
        "src/immich_memories/store/vote_banks.py",
        "src/immich_memories/db/migrations/versions/0004_leases.py",
        "tests/store/test_timing.py",
        "alembic.ini",
    ],
)
def test_a_store_change_runs_the_postgresql_legs(ci_scope, path):
    assert ci_scope.scope([path], event="pull_request").store is True


@pytest.mark.parametrize(
    "path",
    [
        "docker/Dockerfile",
        "docker-compose.yml",
        ".dockerignore",
        "deploy/kubernetes/base/deployment.yaml",
        "services/render-worker/immich_memories_render_worker/worker.py",
        "packages/quadrants/src/quadrants/__init__.py",
        "tests/container/test_upgrade.py",
    ],
)
def test_a_change_to_what_the_image_holds_builds_and_runs_it(ci_scope, path):
    assert ci_scope.scope([path], event="pull_request").container is True


EVERYTHING = {"docs_only": "false", "docs_site": "true", "store": "true", "container": "true"}


@pytest.mark.parametrize(
    "path",
    [
        "pyproject.toml",
        "uv.lock",
        "Makefile",
        ".github/workflows/ci.yml",
        "tests/conftest.py",
        "scripts/ci_scope.py",
        "a-new-top-level-file.toml",
    ],
)
def test_a_file_every_job_depends_on_runs_everything(ci_scope, path):
    scope = ci_scope.scope(["src/immich_memories/analysis/x.py", path], event="pull_request")

    assert scope.as_outputs() == EVERYTHING


def test_an_empty_diff_runs_everything(ci_scope):
    assert ci_scope.scope([], event="pull_request").as_outputs() == EVERYTHING


def test_the_release_runs_everything(ci_scope):
    scope = ci_scope.scope(["docs-site/docs/intro.md"], event="workflow_call")

    assert scope.as_outputs() == EVERYTHING
