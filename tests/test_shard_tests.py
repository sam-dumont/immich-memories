"""CI splits the unit, e2e and feature suites into shards: every test file runs in exactly one."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "shard_tests.py"
DURATIONS = ROOT / "tests" / "shard_durations.json"
WORKFLOWS = ROOT / ".github" / "workflows"
FEATURE_FILES = sorted(
    str(path.relative_to(ROOT)) for path in (ROOT / "tests/integration/features").glob("test_*.py")
)
# What `make test-cov-xml` hands the script: every test file under tests/.
UNIT_FILES = sorted(str(path.relative_to(ROOT)) for path in (ROOT / "tests").rglob("test_*.py"))


@pytest.fixture(scope="module")
def shard_tests():
    spec = importlib.util.spec_from_file_location("shard_tests", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _pick(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], cwd=ROOT, capture_output=True, text=True, check=False
    )


def _e2e_files() -> list[str]:
    """The files `make e2e` runs, as its recipe names them."""
    makefile = (ROOT / "Makefile").read_text()
    recipe = re.search(r"^e2e:.*?\n((?:\t.*\n?)*)", makefile, re.M)
    assert recipe
    return re.findall(r"tests/e2e/test_\w+\.py", recipe.group(1))


def _ci_shards(workflow: str, job: str, variable: str) -> tuple[list[int], int]:
    """The shard numbers a CI job's matrix runs, and the count its make call divides by."""
    steps = yaml.safe_load((WORKFLOWS / workflow).read_text())["jobs"][job]
    commands = "\n".join(str(step.get("run", "")) for step in steps["steps"])
    [total] = {
        int(n) for n in re.findall(rf"{variable}=\$\{{\{{ matrix\.shard \}}\}}/(\d+)", commands)
    }
    return list(steps["strategy"]["matrix"]["shard"]), total


@pytest.mark.parametrize("count", [1, 2, 3, 4])
def test_every_file_lands_in_exactly_one_shard(shard_tests, count):
    files = [f"tests/t/test_{n}.py" for n in range(7)]
    durations = {files[0]: 300.0, files[1]: 120.0, files[2]: 90.0}

    shards = [shard_tests.pick(files, index, count, durations) for index in range(1, count + 1)]

    assert sorted(f for shard in shards for f in shard) == sorted(files)
    assert all(shards)


def test_the_split_ignores_the_order_the_files_come_in(shard_tests):
    files = [f"tests/t/test_{n}.py" for n in range(6)]
    durations = {f: float(n) for n, f in enumerate(files)}

    assert shard_tests.pick(files, 2, 3, durations) == shard_tests.pick(
        list(reversed(files)), 2, 3, durations
    )


def test_the_longest_files_go_to_the_least_loaded_shard(shard_tests):
    durations = {"a.py": 10.0, "b.py": 6.0, "c.py": 5.0, "d.py": 1.0}
    files = list(durations)

    shards = [shard_tests.pick(files, index, 2, durations) for index in (1, 2)]

    assert shards == [["a.py", "d.py"], ["b.py", "c.py"]]


def test_a_file_with_no_recorded_time_counts_as_an_average_one(shard_tests):
    durations = {"a.py": 10.0, "b.py": 10.0, "c.py": 1.0}
    files = [*durations, "new.py"]

    shards = [shard_tests.pick(files, index, 2, durations) for index in (1, 2)]

    # new.py weighs 7 s, the mean, so it is placed third: on the first shard, before c.py.
    assert shards == [["a.py", "new.py"], ["b.py", "c.py"]]


def test_no_shard_runs_every_file():
    result = _pick("pick", "unit", "", "tests/t/test_b.py", "tests/t/test_a.py")

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["tests/t/test_a.py", "tests/t/test_b.py"]


@pytest.mark.parametrize("shard", ["0/3", "4/3", "3", "a/b", "1/0", "2/2"])
def test_a_shard_that_cannot_exist_fails_instead_of_running_nothing(shard):
    # "2/2" over one file: the second shard would be empty, and pytest given no path runs
    # the whole default suite.
    result = _pick("pick", "unit", shard, "tests/t/test_a.py")

    assert result.returncode != 0
    assert result.stdout == ""


def test_recording_sums_each_files_tests_into_its_suite(shard_tests, tmp_path):
    junit = tmp_path / "junit.xml"
    junit.write_text(
        "<testsuites><testsuite>"
        '<testcase classname="tests.e2e.test_web_client" name="a" time="2.5"/>'
        '<testcase classname="tests.e2e.test_web_client" name="b" time="1.5"/>'
        '<testcase classname="tests.integration.features.test_film_hdr" name="c" time="7"/>'
        "</testsuite></testsuites>"
    )
    durations = tmp_path / "durations.json"
    durations.write_text(
        json.dumps({"e2e": {"tests/old/test_kept.py": 3.0}, "unit": {"tests/test_x.py": 1.0}})
    )

    shard_tests.record("e2e", [junit], durations, root=ROOT)

    assert json.loads(durations.read_text()) == {
        "e2e": {
            "tests/e2e/test_web_client.py": 4.0,
            "tests/integration/features/test_film_hdr.py": 7.0,
            "tests/old/test_kept.py": 3.0,
        },
        "unit": {"tests/test_x.py": 1.0},
    }


def test_every_recorded_file_still_exists():
    recorded = json.loads(DURATIONS.read_text())

    assert set(recorded) == {"unit", "e2e", "features"}
    assert [
        path for suite in recorded.values() for path in suite if not (ROOT / path).is_file()
    ] == []


def _assert_the_shards_run_every_file_once(suite: str, shards: list[int], total: int, files):
    picked = [_pick("pick", suite, f"{index}/{total}", *files) for index in shards]

    assert shards == list(range(1, total + 1))
    assert all(result.returncode == 0 for result in picked), [r.stderr for r in picked]
    every = [path for result in picked for path in result.stdout.split()]
    assert sorted(every) == sorted(files)


@pytest.mark.parametrize(
    ("workflow", "job", "variable", "suite", "files"),
    [
        ("ci.yml", "features", "FEATURE_SHARD", "features", FEATURE_FILES),
        ("immich-gate.yml", "features", "FEATURE_SHARD", "features", FEATURE_FILES),
        ("ci.yml", "launch-check", "E2E_SHARD", "e2e", _e2e_files()),
    ],
)
def test_the_ci_shards_run_the_whole_suite_once(workflow, job, variable, suite, files):
    shards, total = _ci_shards(workflow, job, variable)

    _assert_the_shards_run_every_file_once(suite, shards, total, files)


@pytest.mark.parametrize("event", ["pull_request", "push"])
def test_every_unit_cell_runs_every_test_file_once(event):
    scope = _ci_scope_outputs(event)
    cells: dict[tuple[str, str], list[dict]] = {}
    for leg in json.loads(scope["unit_matrix"])["include"]:
        cells.setdefault((leg["os"], leg["python-version"]), []).append(leg)

    for legs in cells.values():
        [total] = {leg["shards"] for leg in legs}
        _assert_the_shards_run_every_file_once(
            "unit", sorted(leg["shard"] for leg in legs), total, UNIT_FILES
        )


def test_the_unit_job_runs_the_shard_its_matrix_leg_names():
    job = yaml.safe_load((WORKFLOWS / "ci.yml").read_text())["jobs"]["test"]
    commands = "\n".join(str(step.get("run", "")) for step in job["steps"])

    assert job["strategy"]["matrix"] == "${{ fromJSON(needs.changes.outputs.unit_matrix) }}"
    assert re.search(
        r"^\s*make test-cov-xml TEST_SHARD=\$\{\{ matrix\.shard \}\}/\$\{\{ matrix\.shards \}\}\s*$",
        commands,
        re.M,
    )


def _ci_scope_outputs(event: str) -> dict[str, str]:
    """What the `changes` job answers for a Python change, on a pull request or main."""
    spec = importlib.util.spec_from_file_location("ci_scope", ROOT / "scripts" / "ci_scope.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module  # dataclasses resolve the owning module by name
    spec.loader.exec_module(module)
    return module.outputs(["src/immich_memories/cli/__init__.py"], event=event)
