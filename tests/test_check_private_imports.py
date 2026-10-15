"""`make private-imports`: no module reaches into another's private names or a stage's internals."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_private_imports.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_private_imports", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _findings(gate, tmp_path: Path, source: str) -> list[str]:
    path = tmp_path / "caller.py"
    path.write_text(source)
    return [finding.message for finding in gate.check_file(path)]


def test_importing_another_modules_private_name_is_a_finding(gate, tmp_path):
    found = _findings(gate, tmp_path, "from immich_memories.config.unsupported import _said\n")

    assert found == ["imports private _said from immich_memories.config.unsupported"]


def test_reading_a_private_name_off_an_imported_module_is_a_finding(gate, tmp_path):
    source = "from immich_memories.config import unsupported\n\nunsupported._said.clear()\n"

    assert _findings(gate, tmp_path, source) == [
        "reads private _said off immich_memories.config.unsupported"
    ]


def test_a_stage_module_outside_its_all_is_internal_to_the_stage(gate, tmp_path):
    found = _findings(gate, tmp_path, "from immich_memories.analysis.polish.refill import X\n")

    assert found == [
        "immich_memories.analysis.polish.refill is internal to immich_memories.analysis.polish; "
        "import one of the modules its __all__ lists"
    ]


def test_public_names_and_listed_stage_modules_are_fine(gate, tmp_path):
    source = (
        "from immich_memories.analysis.polish import layer\n"
        "from immich_memories.analysis.polish.layer import ThinPolish\n"
        "from immich_memories.config.unsupported import every_warning_said_again\n"
        "from os import _exit\n"
    )

    assert _findings(gate, tmp_path, source) == []


def test_the_repository_reaches_into_nothing(gate, capsys):
    assert gate.main([]) == 0
