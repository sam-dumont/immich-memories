"""Free-space preflight: an output film that can't fit stops before it renders."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from immich_memories.operations.disk_guard import (
    InsufficientDiskSpace,
    estimate_output_bytes,
    low_space_warning,
    require_room_for_film,
    volume_space,
)


def test_a_higher_quality_target_estimates_a_bigger_file() -> None:
    """CRF 18 (`high`) is the richer picture the calibration table anchors at 4.6 Mbps."""
    high = estimate_output_bytes(60.0, crf=18)
    balanced = estimate_output_bytes(60.0, crf=24)

    assert high > balanced > 0


def test_a_longer_film_estimates_proportionally_more() -> None:
    short = estimate_output_bytes(30.0, crf=24)
    long_ = estimate_output_bytes(300.0, crf=24)

    assert long_ == pytest.approx(short * 10, rel=0.01)


def test_zero_duration_estimates_nothing() -> None:
    assert estimate_output_bytes(0.0, crf=24) == 0


def test_volume_space_reads_the_real_filesystem(tmp_path: Path) -> None:
    found = volume_space("output", tmp_path)

    assert found is not None
    assert found.path == tmp_path
    assert found.free_bytes == shutil.disk_usage(tmp_path).free


def test_volume_space_reads_the_parent_of_a_directory_not_yet_created(tmp_path: Path) -> None:
    missing = tmp_path / "not-created-yet"

    found = volume_space("output", missing)

    assert found is not None
    assert found.free_bytes == shutil.disk_usage(tmp_path).free


def _volume(free_bytes: int, tmp_path: Path):
    from immich_memories.operations.disk_guard import VolumeSpace

    return VolumeSpace(label="output", path=tmp_path, free_bytes=free_bytes)


def test_plenty_of_room_warns_about_nothing(tmp_path: Path) -> None:
    assert low_space_warning(_volume(20 * 1024**3, tmp_path), min_free_gb=5.0) is None


def test_low_free_space_names_the_volume_and_what_to_do(tmp_path: Path) -> None:
    warning = low_space_warning(_volume(int(2.5 * 1024**3), tmp_path), min_free_gb=5.0)

    assert warning is not None
    assert "output" in warning
    assert str(tmp_path) in warning
    assert "2.5" in warning
    assert "runs delete" in warning


def test_a_film_that_fits_raises_nothing(tmp_path: Path) -> None:
    require_room_for_film(_volume(10 * 1024**3, tmp_path), estimated_bytes=1024**3)


def test_a_film_that_cannot_fit_names_the_volume_the_free_space_and_the_estimate(
    tmp_path: Path,
) -> None:
    with pytest.raises(InsufficientDiskSpace) as caught:
        require_room_for_film(_volume(int(0.5 * 1024**3), tmp_path), estimated_bytes=2 * 1024**3)

    message = str(caught.value)
    assert "output" in message
    assert str(tmp_path) in message
    assert "0.5" in message
    assert "2.0" in message
    assert "runs delete" in message
