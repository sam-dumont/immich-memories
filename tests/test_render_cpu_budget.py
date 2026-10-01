"""Automatic rendering budgets use the CPU capacity a container may consume."""

import os

import pytest

from immich_memories.processing.memory_budget import source_prepare_workers


def test_one_cpu_quota_limits_automatic_workers_despite_host_affinity(tmp_path, monkeypatch):
    (tmp_path / "memory.max").write_text(str(16 * 2**30))
    (tmp_path / "cpu.max").write_text("100000 100000\n")
    monkeypatch.setattr(os, "sched_getaffinity", lambda _pid: set(range(32)), raising=False)

    workers, _reason = source_prepare_workers("auto", cgroup_root=tmp_path)

    assert workers == 1


def test_legacy_cpu_quota_limits_automatic_workers(tmp_path, monkeypatch):
    (tmp_path / "memory.max").write_text(str(16 * 2**30))
    cpu = tmp_path / "cpu"
    cpu.mkdir()
    (cpu / "cpu.cfs_quota_us").write_text("50000\n")
    (cpu / "cpu.cfs_period_us").write_text("100000\n")
    monkeypatch.setattr(os, "sched_getaffinity", lambda _pid: set(range(32)), raising=False)

    workers, _reason = source_prepare_workers("auto", cgroup_root=tmp_path)

    assert workers == 1


def test_decoder_passes_effective_cpu_capacity_to_filter_pools(tmp_path, monkeypatch):
    import subprocess

    from immich_memories.processing import memory_budget
    from immich_memories.processing.streaming_frame_decoder import FrameDecoder

    (tmp_path / "cpu.max").write_text("150000 100000\n")
    monkeypatch.setattr(memory_budget, "_CGROUP", tmp_path)
    monkeypatch.setattr(os, "sched_getaffinity", lambda _pid: set(range(32)), raising=False)
    commands = []

    def start(command, **_kwargs):
        commands.append(command)
        raise OSError("captured FFmpeg launch")

    # WHY: capture the actual process boundary, without decoding a fake source.
    monkeypatch.setattr(subprocess, "Popen", start)
    decoder = FrameDecoder(tmp_path / "source.mov", 2160, 3840, 60, threads=1)
    with pytest.raises(OSError, match="captured FFmpeg launch"):
        next(iter(decoder))

    (command,) = commands
    assert command[command.index("-filter_threads") + 1] == "2"
    assert command[command.index("-filter_complex_threads") + 1] == "2"
    assert command[command.index("-threads") + 1] == "1"


def test_unavailable_affinity_falls_back_to_host_count_and_quota(tmp_path, monkeypatch):
    from immich_memories.processing.memory_budget import available_cpus

    def unavailable(_pid):
        raise OSError("affinity is unavailable")

    (tmp_path / "cpu.max").write_text("300000 100000\n")
    monkeypatch.setattr(os, "sched_getaffinity", unavailable, raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 18)

    assert available_cpus(tmp_path) == 3


@pytest.mark.parametrize(
    ("quota", "affinity", "expected"),
    [
        ("max 100000", 18, 18),
        ("250000 100000", 18, 3),
        ("800000 100000", 4, 4),
        ("50000 100000", 10, 1),
        ("0 100000", 10, 10),
        ("100000 0", 10, 10),
        ("broken", 10, 10),
        ("", 10, 10),
        ("100000 100000 extra", 10, 10),
    ],
)
def test_quota_never_exceeds_affinity_or_turns_unusable_data_into_zero_cpus(
    tmp_path, monkeypatch, quota, affinity, expected
):
    from immich_memories.processing.memory_budget import available_cpus

    (tmp_path / "cpu.max").write_text(quota)
    monkeypatch.setattr(os, "sched_getaffinity", lambda _pid: set(range(affinity)), raising=False)

    assert available_cpus(tmp_path) == expected


@pytest.mark.parametrize("directory", ["cpu", "cpu,cpuacct", "."])
@pytest.mark.parametrize(("quota", "expected"), [("200000", 2), ("-1", 18)])
def test_legacy_mount_locations_and_unlimited_quota(
    tmp_path, monkeypatch, directory, quota, expected
):
    from immich_memories.processing.memory_budget import available_cpus

    cpu = tmp_path / directory
    cpu.mkdir(exist_ok=True)
    (cpu / "cpu.cfs_quota_us").write_text(quota)
    (cpu / "cpu.cfs_period_us").write_text("100000")
    monkeypatch.setattr(os, "sched_getaffinity", lambda _pid: set(range(18)), raising=False)

    assert available_cpus(tmp_path) == expected


def test_host_detection_without_affinity_or_cgroups(tmp_path, monkeypatch):
    from immich_memories.processing.memory_budget import available_cpus

    monkeypatch.delattr(os, "sched_getaffinity", raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 18)
    assert available_cpus(tmp_path) == 18
    monkeypatch.setattr(os, "cpu_count", lambda: None)
    assert available_cpus(tmp_path) == 1
