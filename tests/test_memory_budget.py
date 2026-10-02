"""Photo preparation runs as many at once as the memory this process may use allows (#1527)."""

from __future__ import annotations

import pytest

from immich_memories.processing.memory_budget import (
    MemoryBudget,
    memory_budget,
    prepare_workers,
    source_prepare_workers,
)

GIB = 2**30


@pytest.mark.parametrize(
    ("gigabytes", "workers"),
    [(2, 1), (3, 1), (4, 1), (6, 1), (8, 2), (16, 2), (1, 1), (3.8, 1), (1.9, 1)],
)
def test_workers_leave_parent_reserve_before_admitting_sources(gigabytes, workers):
    assert prepare_workers(int(gigabytes * GIB), cpus=8) == workers


def test_a_one_cpu_box_prepares_one_at_a_time():
    assert prepare_workers(16 * GIB, cpus=1) == 1


def test_unknown_memory_keeps_the_old_default():
    assert prepare_workers(None, cpus=8) == 2


def test_a_container_limit_below_physical_ram_is_the_budget(tmp_path):
    (tmp_path / "memory.max").write_text(f"{2 * GIB}\n")
    budget = memory_budget(tmp_path, physical=16 * GIB)
    assert budget == MemoryBudget(2 * GIB, "container limit")


def test_an_unlimited_cgroup_falls_back_to_physical_ram(tmp_path):
    (tmp_path / "memory.max").write_text("max\n")
    assert memory_budget(tmp_path, physical=16 * GIB) == MemoryBudget(16 * GIB, "physical RAM")


def test_a_cgroup_v1_sentinel_is_not_a_limit(tmp_path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "memory.limit_in_bytes").write_text("9223372036854771712\n")
    assert memory_budget(tmp_path, physical=8 * GIB) == MemoryBudget(8 * GIB, "physical RAM")


def test_a_cgroup_v1_limit_is_read(tmp_path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "memory.limit_in_bytes").write_text(f"{4 * GIB}\n")
    assert memory_budget(tmp_path, physical=16 * GIB) == MemoryBudget(4 * GIB, "container limit")


def test_no_cgroup_means_physical_ram(tmp_path):
    assert memory_budget(tmp_path, physical=8 * GIB) == MemoryBudget(8 * GIB, "physical RAM")


def test_auto_reads_the_container_and_says_why(tmp_path):
    (tmp_path / "memory.max").write_text(f"{2 * GIB}\n")
    workers, reason = source_prepare_workers("auto", cgroup_root=tmp_path, cpus=4)
    assert workers == 1
    assert reason == "1 at a time (2.0 GB available, container limit)"


def test_an_explicit_setting_always_wins(tmp_path):
    (tmp_path / "memory.max").write_text(f"{2 * GIB}\n")
    workers, reason = source_prepare_workers(3, cgroup_root=tmp_path, cpus=4)
    assert workers == 3
    assert reason == "3 at a time (set in the config)"


def test_the_config_defaults_to_auto_and_still_takes_a_number():
    from immich_memories.config_models_analysis import AnalysisConfig

    assert AnalysisConfig().source_prepare_workers == "auto"
    assert AnalysisConfig(source_prepare_workers=3).source_prepare_workers == 3
    with pytest.raises(ValueError):
        AnalysisConfig(source_prepare_workers=9)


def test_preflight_says_how_many_sources_a_render_prepares():
    from immich_memories.config import Config
    from immich_memories.preflight_run import check_memory

    config = Config()
    config.analysis.source_prepare_workers = 1
    assert check_memory(config).message.startswith(
        "Photo preparation: 1 at a time (set in the config); libx265 lookahead at 4K: "
    )
    config.analysis.source_prepare_workers = "auto"
    assert check_memory(config).message.startswith("Photo preparation: ")


def test_four_gib_container_leaves_room_for_parent_during_photo_preparation(tmp_path):
    (tmp_path / "memory.max").write_text(f"{4 * GIB}\n")
    workers, _reason = source_prepare_workers("auto", cgroup_root=tmp_path, cpus=4)
    assert workers == 1


@pytest.mark.parametrize(
    ("encoder", "gib", "cpus", "width", "height", "expected"),
    [
        ("hevc_videotoolbox", 4, 4, 1920, 1080, True),
        ("hevc_videotoolbox", 3, 4, 1920, 1080, False),
        ("hevc_videotoolbox", 4, 1, 1920, 1080, False),
        ("hevc_videotoolbox", 4, 4, 640, 480, False),
        ("hevc_nvenc", 4, 4, 1920, 1080, False),
        ("libx265", 4, 4, 1920, 1080, False),
    ],
)
def test_read_ahead_requires_a_beneficial_encoder_and_resource_headroom(
    tmp_path, monkeypatch, encoder, gib, cpus, width, height, expected
):
    import importlib

    budgets = importlib.import_module("immich_memories.processing.memory_budget")
    (tmp_path / "memory.max").write_text(str(gib * GIB))
    (tmp_path / "cpu.max").write_text(f"{cpus * 100000} 100000")
    # WHY: Use real cgroup files to exercise resource admission without host limits.
    monkeypatch.setattr(budgets, "_CGROUP", tmp_path)
    assert budgets.assembly_frame_read_ahead(width, height, encoder=encoder) is expected
