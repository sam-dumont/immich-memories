"""Disk space preflight: a film that cannot fit stops before it renders."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from immich_memories.config_loader import Config
from immich_memories.generate import GenerationError, check_disk_space
from tests.conftest import make_clip


def _usage(free_bytes: int):
    return type("Usage", (), {"free": free_bytes})()


class TestCheckDiskSpace:
    """`check_disk_space` reads the output and cache volumes before a film renders."""

    def test_raises_when_the_estimated_film_cannot_fit(self, tmp_path: Path):
        # WHY: shutil.disk_usage reads the real volume; a boundary this preflight always crosses.
        with (
            patch(
                "immich_memories.operations.disk_guard.shutil.disk_usage",
                return_value=_usage(100_000),
            ),
            pytest.raises(GenerationError, match="Not enough free space"),
        ):
            check_disk_space(Config(), tmp_path, estimated_duration_seconds=600)

    def test_passes_with_plenty_of_room(self, tmp_path: Path):
        with patch(
            "immich_memories.operations.disk_guard.shutil.disk_usage",
            return_value=_usage(20 * 1024**3),
        ):
            warnings = check_disk_space(Config(), tmp_path, estimated_duration_seconds=60)

        assert warnings == []

    def test_warns_below_the_threshold_even_when_the_film_still_fits(self, tmp_path: Path):
        config = Config()
        config.output.min_free_space_gb = 5.0
        with patch(
            "immich_memories.operations.disk_guard.shutil.disk_usage",
            # 2 GB free: below the 5 GB warning line, but far more than a 10s film needs.
            return_value=_usage(2 * 1024**3),
        ):
            warnings = check_disk_space(config, tmp_path, estimated_duration_seconds=10)

        assert any("Low disk space" in warning for warning in warnings)
        assert any(str(tmp_path) in warning for warning in warnings)

    def test_error_names_the_volume_the_free_space_and_the_estimate(self, tmp_path: Path):
        with (
            patch(
                "immich_memories.operations.disk_guard.shutil.disk_usage",
                return_value=_usage(100_000),
            ),
            pytest.raises(GenerationError) as caught,
        ):
            check_disk_space(Config(), tmp_path, estimated_duration_seconds=600)

        message = str(caught.value)
        assert str(tmp_path) in message
        assert "runs delete" in message


def test_a_run_on_a_full_disk_stops_before_it_downloads_anything(tmp_path: Path):
    from immich_memories.generate import GenerationParams, generate_memory

    client = MagicMock()  # WHY: Immich must not be asked for a single clip
    params = GenerationParams(
        clips=[make_clip("c1")], output_path=tmp_path / "out.mp4", config=Config(), client=client
    )

    # WHY: a disk with next to nothing left, far below what even a 5s clip needs.
    with (
        patch(
            "immich_memories.operations.disk_guard.shutil.disk_usage",
            return_value=_usage(100_000),
        ),
        pytest.raises(GenerationError, match="Not enough free space"),
    ):
        generate_memory(params)

    assert client.mock_calls == []
