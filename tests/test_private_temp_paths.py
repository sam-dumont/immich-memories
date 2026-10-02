"""Scratch files kept under the system temp dir live in this user's private directory."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from immich_memories.processing.caption_image import CaptionStyle, render_caption

_FONT = Path(__file__).parents[1] / "src/immich_memories/titles/bundled_fonts/outfit/latin-700-normal.ttf"


@pytest.fixture
def system_temp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    return tmp_path


def _private_root(system_temp: Path) -> Path:
    return system_temp / f"immich-memories-{os.getuid()}"


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_caption_images_are_written_under_the_private_temp_dir(system_temp: Path) -> None:
    style = CaptionStyle(str(_FONT), 40, (255, 255, 255), 2, 1)

    path, _, _ = render_caption("Αθήνα", style)

    assert path.is_relative_to(_private_root(system_temp))
    assert _mode(path.parent) == 0o700


def test_the_kernel_cache_falls_back_to_the_private_temp_dir(
    system_temp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from immich_memories.titles.kernel_backend_probe import kernel_cache_dir

    unwritable_home = system_temp / "home"
    unwritable_home.mkdir(mode=0o500)
    monkeypatch.setenv("HOME", str(unwritable_home))
    kernel_cache_dir.cache_clear()
    try:
        cache = kernel_cache_dir()
    finally:
        kernel_cache_dir.cache_clear()
        unwritable_home.chmod(0o700)

    assert cache is not None
    assert cache.is_relative_to(_private_root(system_temp))
    assert _mode(cache) == 0o700


def test_a_store_without_a_file_takes_its_import_lock_in_the_private_temp_dir(
    system_temp: Path,
) -> None:
    from immich_memories.store.legacy_imports import _import_lease

    store = SimpleNamespace(location=SimpleNamespace(sqlite_path=None))

    lease = _import_lease(store)  # type: ignore[arg-type]

    assert lease.lock_path.is_relative_to(_private_root(system_temp))
    assert _mode(lease.lock_path.parent) == 0o700
