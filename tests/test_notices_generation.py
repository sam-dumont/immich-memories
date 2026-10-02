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
