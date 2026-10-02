"""Notice checks stay useful in the lightweight CI environment."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_inventory_check_works_without_optional_packages(tmp_path):
    (tmp_path / "scripts").mkdir()
    for name in ("uv.lock", "THIRD_PARTY_NOTICES", "THIRD_PARTY_NOTICES.in"):
        shutil.copyfile(ROOT / name, tmp_path / name)
    shutil.copyfile(
        ROOT / "scripts/generate_third_party_notices.py",
        tmp_path / "scripts/generate_third_party_notices.py",
    )
    before = (tmp_path / "THIRD_PARTY_NOTICES").read_text()
    result = subprocess.run(
        [sys.executable, "-S", str(tmp_path / "scripts/generate_third_party_notices.py")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "THIRD_PARTY_NOTICES").read_text() == before


@pytest.mark.parametrize("replacement", ["", "fsspec 0.0.0\n  License: BSD-3-Clause\n"])
def test_missing_or_mismatched_inventory_metadata_requires_review(tmp_path, replacement):
    (tmp_path / "scripts").mkdir()
    for name in ("uv.lock", "THIRD_PARTY_NOTICES", "THIRD_PARTY_NOTICES.in"):
        shutil.copyfile(ROOT / name, tmp_path / name)
    shutil.copyfile(
        ROOT / "scripts/generate_third_party_notices.py",
        tmp_path / "scripts/generate_third_party_notices.py",
    )
    inventory = tmp_path / "THIRD_PARTY_NOTICES"
    inventory.write_text(
        re.sub(
            r"^fsspec [^\n]+\n(?:  [^\n]+\n)+",
            replacement,
            inventory.read_text(),
            flags=re.MULTILINE,
        )
    )
    result = subprocess.run(
        [sys.executable, "-S", str(tmp_path / "scripts/generate_third_party_notices.py")],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert re.search(r"^fsspec [^\n]+\n  License: UNKNOWN$", inventory.read_text(), re.MULTILINE)


def test_no_python_runtime_dependency_carries_a_gpl_licence():
    """The project is MIT: a GPL library imported in-process would bind every image we ship.

    LGPL is fine (imported, replaceable); GPL programs we only run as subprocesses
    (FFmpeg, ExifTool) sit above the Python section and are not checked here.
    """
    notices = (ROOT / "THIRD_PARTY_NOTICES").read_text(encoding="utf-8")
    python_section = notices.split("\nPython dependencies\n", 1)[1]
    entries = re.findall(r"^(\S+ \S+)\n  License: (.+)$", python_section, flags=re.MULTILINE)
    gpl = [
        name
        for name, licence in entries
        if ("GPL" in licence or "General Public License" in licence)
        and "LGPL" not in licence
        and "Lesser" not in licence
    ]

    assert gpl == []
