"""The cognitive-complexity watermark keys functions by name, so a line shift changes nothing (#1550)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "complexity_watermark.py"


@pytest.fixture(scope="module")
def watermark():
    spec = importlib.util.spec_from_file_location("complexity_watermark", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _row(path: str, name: str, complexity: int) -> dict:
    return {"path": path, "function_name": name, "complexity": complexity, "file_name": "x.py"}


def _run(watermark, tmp_path, recorded: dict, rows: list[dict]) -> tuple[int, Path]:
    file = tmp_path / "complexity-watermark.json"
    file.write_text(watermark.render(recorded))
    results = tmp_path / "complexipy_results_1.json"
    results.write_text(json.dumps(rows))
    return watermark.main(["--watermark", str(file), str(results)]), file


def test_a_function_that_only_moved_leaves_the_file_byte_for_byte(watermark, tmp_path):
    recorded = {"src/a.py": {"Runner::run": [19]}}
    before = watermark.render(recorded)

    status, file = _run(watermark, tmp_path, recorded, [_row("src/a.py", "Runner::run", 19)])

    assert status == 0
    assert file.read_text() == before
    assert "line" not in before


def test_a_new_function_over_the_limit_fails_and_writes_nothing(watermark, tmp_path, capsys):
    recorded = {"src/a.py": {"Runner::run": [19]}}
    before = watermark.render(recorded)

    status, file = _run(
        watermark,
        tmp_path,
        recorded,
        [_row("src/a.py", "Runner::run", 19), _row("src/b.py", "plan", 16)],
    )

    assert status == 1
    assert file.read_text() == before
    assert "src/b.py" in capsys.readouterr().out


def test_a_recorded_function_that_got_worse_fails(watermark, tmp_path):
    status, _ = _run(
        watermark, tmp_path, {"src/a.py": {"run": [19]}}, [_row("src/a.py", "run", 21)]
    )

    assert status == 1


def test_a_second_function_of_the_same_name_is_new_not_absorbed(watermark, tmp_path):
    status, _ = _run(
        watermark,
        tmp_path,
        {"src/a.py": {"run": [19]}},
        [_row("src/a.py", "run", 19), _row("src/a.py", "run", 16)],
    )

    assert status == 1


def test_a_function_that_improved_tightens_the_watermark(watermark, tmp_path):
    recorded = {"src/a.py": {"run": [19]}, "src/b.py": {"plan": [22]}}

    status, file = _run(watermark, tmp_path, recorded, [_row("src/b.py", "plan", 18)])

    assert status == 0
    assert json.loads(file.read_text()) == {"src/b.py": {"plan": [18]}}


def test_the_file_is_sorted_so_two_branches_write_the_same_text(watermark):
    one = {"src/b.py": {"z": [17], "a": [16]}, "src/a.py": {"run": [20, 16]}}
    two = {"src/a.py": {"run": [16, 20]}, "src/b.py": {"a": [16], "z": [17]}}

    assert watermark.render(one) == watermark.render(two)


def test_no_results_file_is_an_analyzer_failure_not_a_pass(watermark, tmp_path):
    file = tmp_path / "complexity-watermark.json"
    file.write_text(watermark.render({}))

    assert watermark.main(["--watermark", str(file)]) == 2
