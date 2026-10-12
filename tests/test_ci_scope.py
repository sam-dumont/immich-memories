"""A pull request runs the jobs its changed files can break, and a file nobody classified runs them all."""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci_scope.py"


@pytest.fixture(scope="module")
def ci_scope():
    spec = importlib.util.spec_from_file_location("ci_scope", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module  # dataclasses resolve the owning module by name
    spec.loader.exec_module(module)
    return module


def _running(ci_scope, paths: list[str], event: str = "pull_request") -> set[str]:
    outputs = ci_scope.scope(paths, event=event).as_outputs()
    return {name for name, value in outputs.items() if value == "true"}


ALL_JOBS = {
    "docs_site",
    "store",
    "container",
    "python",
    "unit",
    "package",
    "launch",
    "immich",
    "render_worker",
    "extras",
}


def test_a_selection_change_runs_the_app_suites_on_sqlite_only(ci_scope):
    running = _running(
        ci_scope,
        [
            "src/immich_memories/analysis/editorial_story_slots.py",
            "tests/test_editorial_story_slots.py",
        ],
    )

    assert running == {"python", "unit", "package", "launch", "immich", "extras"}


def test_a_docs_page_change_builds_the_site_and_runs_no_test_job(ci_scope):
    running = _running(ci_scope, ["docs-site/docs/how-it-chooses/selection.md", "ARCHITECTURE.md"])

    assert running == {"docs_only", "docs_site"}


def test_a_page_the_feature_suites_read_runs_them(ci_scope):
    # tests/integration/features/test_store_and_runs.py reads the upgrading page.
    running = _running(ci_scope, ["docs-site/docs/run/maintenance/upgrading.md"])

    assert {"docs_only", "docs_site", "launch", "immich"} == running


def test_a_test_only_change_runs_the_unit_suite_and_nothing_heavy(ci_scope):
    running = _running(
        ci_scope, ["tests/test_editorial_story_slots.py", "tests/editorial_story_fixtures.py"]
    )

    assert running == {"python", "unit"}


def test_an_immich_client_change_runs_the_real_immich_gate(ci_scope):
    running = _running(ci_scope, ["src/immich_memories/api/immich.py"])

    assert {"immich", "launch", "unit", "package", "render_worker"} <= running
    assert not {"docs_site", "store", "container"} & running


@pytest.mark.parametrize(
    "path",
    [
        "tests/integration/immich_gate/seed.py",
        "tests/integration/native_sharing/test_owner_reads.py",
        "tests/integration/features/real_seed.py",
        "tests/e2e/fake_library.py",
        "tests/immich_fakes.py",
        "scripts/immich_gate_images.sh",
    ],
)
def test_the_fakes_the_seeding_and_the_gate_suites_run_the_gate(ci_scope, path):
    assert "immich" in _running(ci_scope, [path])


def test_a_web_client_change_runs_the_browser_suites_on_one_cell(ci_scope):
    running = _running(ci_scope, ["web/src/lib/RenderPanel.svelte"])

    assert running == {"unit", "package", "launch", "immich"}


def test_a_web_route_change_runs_the_browser_suites(ci_scope):
    running = _running(ci_scope, ["src/immich_memories/web/job_routes.py"])

    assert {"launch", "immich", "unit", "python"} <= running
    assert "render_worker" not in running


@pytest.mark.parametrize(
    "path",
    [
        "services/render-worker/immich_memories_render_worker/worker.py",
        "src/immich_memories/processing/remote_render.py",
        "src/immich_memories/titles/rendering_service.py",
        "src/immich_memories/config_loader.py",
    ],
)
def test_the_render_worker_runs_for_itself_and_the_app_code_it_imports(ci_scope, path):
    assert "render_worker" in _running(ci_scope, [path])


def test_the_render_worker_skips_app_code_it_never_imports(ci_scope):
    assert "render_worker" not in _running(ci_scope, ["src/immich_memories/people/graph.py"])


def test_the_extras_list_names_every_test_marked_extras(ci_scope):
    marked = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "tests").rglob("test_*.py")
        if re.search(
            r"^\s*(@pytest\.mark\.extras|pytestmark = pytest\.mark\.extras)",
            path.read_text(encoding="utf-8"),
            re.M,
        )
    }

    assert marked <= set(ci_scope.EXTRAS_TESTS)


def test_the_extras_run_for_their_tests_and_skip_unrelated_code(ci_scope):
    assert "extras" in _running(ci_scope, ["tests/test_local_reader.py"])
    assert "extras" in _running(ci_scope, ["src/immich_memories/audio/generators/demucs_local.py"])
    assert "extras" not in _running(ci_scope, ["src/immich_memories/web/job_routes.py"])


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


def test_an_image_change_runs_the_unit_suite_on_one_cell(ci_scope):
    running = _running(ci_scope, ["docker/Dockerfile"])

    assert running == {"container", "unit"}


EVERYTHING = {"docs_only": "false", **dict.fromkeys(ALL_JOBS, "true")}


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


def test_a_path_no_rule_knows_runs_everything_even_beside_docs(ci_scope):
    scope = ci_scope.scope(
        ["docs-site/docs/intro.md", "a-new-top-level-file.toml"], event="pull_request"
    )

    assert scope.as_outputs() == EVERYTHING


def test_an_empty_diff_runs_everything(ci_scope):
    assert ci_scope.scope([], event="pull_request").as_outputs() == EVERYTHING


@pytest.mark.parametrize("event", ["push", "workflow_call", "workflow_dispatch", "schedule"])
def test_main_the_release_and_the_nightly_run_everything(ci_scope, event):
    # A push to main, the release (workflow_dispatch, or workflow_call from it) and the
    # nightly (schedule) are never scoped, whatever the diff holds.
    scope = ci_scope.scope(["docs-site/docs/intro.md"], event=event)

    assert scope.as_outputs() == EVERYTHING


def test_every_output_is_an_output_of_the_ci_change_scope_job():
    workflow = yaml_load(ROOT / ".github" / "workflows" / "ci.yml")
    outputs = set(workflow["jobs"]["changes"]["outputs"])
    gate = set(
        yaml_load(ROOT / ".github" / "workflows" / "immich-gate.yml")["jobs"]["changes"]["outputs"]
    )

    assert (ALL_JOBS | {"docs_only"}) - {"immich"} <= outputs
    assert {"immich", "store"} <= gate


def test_the_script_writes_github_outputs_for_a_push(tmp_path):
    sink = tmp_path / "github-output"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--event", "push"],
        cwd=ROOT,
        env={"GITHUB_OUTPUT": str(sink), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=True,
    )

    written = dict(line.split("=", 1) for line in sink.read_text().splitlines())
    assert written == EVERYTHING
    assert result.stdout.splitlines() == sink.read_text().splitlines()


def yaml_load(path: Path) -> dict:
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ── How the workflows read the scope ────────────────────────────────────────

WORKFLOWS = ROOT / ".github" / "workflows"
# Job -> the scope output its `if:` reads.
CI_JOBS = {
    "test": "unit",
    "test-extras": "extras",
    "test-store": "store",
    "build": "package",
    "docker": "container",
    "container-e2e": "container",
    "docs": "docs_site",
    "docs-tests": "docs_only",
    "launch-check": "launch",
    "render-worker": "render_worker",
}


def _on(workflow: dict) -> dict:
    return workflow.get("on") or workflow.get(True)  # PyYAML reads a bare `on:` as True


def test_ci_runs_on_every_pull_request_every_push_to_main_and_every_release_call():
    triggers = _on(yaml_load(WORKFLOWS / "ci.yml"))

    assert "pull_request" in triggers
    assert triggers["push"] == {"branches": ["main"]}
    assert "workflow_call" in triggers
    assert not (WORKFLOWS / "main-push.yml").exists()  # ci.yml on main replaced the tripwire


def test_the_immich_gate_runs_on_main_and_can_be_called_by_the_release():
    triggers = _on(yaml_load(WORKFLOWS / "immich-gate.yml"))

    assert {"pull_request", "push", "workflow_call"} <= set(triggers)


@pytest.mark.parametrize(
    ("name", "prefix"), [("ci.yml", "ci-"), ("immich-gate.yml", "immich-gate-")]
)
def test_only_a_pull_request_cancels_its_older_run(name, prefix):
    # A merge to main or a release cancelling another would leave a commit unchecked;
    # and the release calls both workflows, which must not share a group.
    concurrency = yaml_load(WORKFLOWS / name)["concurrency"]

    assert concurrency["group"] == (
        prefix + "${{ github.event_name == 'pull_request' && github.ref || github.run_id }}"
    )
    assert "github.workflow" not in concurrency["group"]


@pytest.mark.parametrize(("job", "output"), sorted(CI_JOBS.items()))
def test_each_heavy_ci_job_reads_its_own_scope(job, output):
    jobs = yaml_load(WORKFLOWS / "ci.yml")["jobs"]
    condition = " ".join(str(jobs[job]["if"]).split())

    assert f"needs.changes.outputs.{output} == 'true'" in condition
    assert "event_name" not in condition  # main and the release run it: the scope says when


def test_ci_success_waits_for_every_job():
    jobs = yaml_load(WORKFLOWS / "ci.yml")["jobs"]

    assert set(jobs["ci-success"]["needs"]) == set(jobs) - {"ci-success"}


@pytest.mark.parametrize("job", ["immich", "features"])
def test_the_real_immich_runs_read_the_immich_scope(job):
    condition = yaml_load(WORKFLOWS / "immich-gate.yml")["jobs"][job]["if"]

    assert "needs.changes.outputs.immich == 'true'" in condition


def _immich_gate(scope: str, immich: str, features: str, in_scope: str) -> int:
    step = yaml_load(WORKFLOWS / "immich-gate.yml")["jobs"]["gate"]["steps"][0]
    env = {
        "SCOPE": scope,
        "IMMICH": immich,
        "FEATURES": features,
        "IN_SCOPE": in_scope,
        "PATH": "/usr/bin:/bin",
    }
    return subprocess.run(
        ["bash", "-c", step["run"]], env=env, capture_output=True, check=False
    ).returncode


@pytest.mark.parametrize(
    ("scope", "immich", "features", "in_scope", "passes"),
    [
        ("success", "skipped", "skipped", "false", True),  # nothing a real Immich reads changed
        ("success", "success", "success", "true", True),
        ("success", "skipped", "skipped", "true", False),  # in scope but never ran
        ("success", "success", "failure", "true", False),
        ("failure", "skipped", "skipped", "", False),  # no scope, no verdict
    ],
)
def test_the_immich_gate_rollup_passes_only_what_ran_or_was_out_of_scope(
    scope, immich, features, in_scope, passes
):
    assert (_immich_gate(scope, immich, features, in_scope) == 0) is passes
