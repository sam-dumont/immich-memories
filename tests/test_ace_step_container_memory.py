"""Local music must fit the container's remaining memory, not the host's RAM."""

import pytest

from immich_memories.audio.generators import memory_budget

GIB = 2**30


def test_a_busy_v2_container_refuses_weights_that_fit_the_host(tmp_path, monkeypatch):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(f"MemAvailable: {32 * GIB // 1024} kB\n")
    (tmp_path / "memory.max").write_text(str(10 * GIB))
    (tmp_path / "memory.current").write_text(str(9 * GIB))
    # WHY: Linux procfs and cgroup counters are filesystem boundaries; keep their real format.
    monkeypatch.setattr(memory_budget.platform, "system", lambda: "Linux")
    monkeypatch.setattr(memory_budget, "_MEMINFO_PATH", meminfo)
    monkeypatch.setattr(memory_budget, "_CGROUP", tmp_path, raising=False)

    shortfall = memory_budget.memory_shortfall("acestep-v15-turbo", None)

    assert shortfall is not None
    assert shortfall.available_bytes == GIB
    assert shortfall.required_bytes == 7 * GIB


def test_a_busy_v1_container_also_refuses_the_profile(tmp_path, monkeypatch):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(f"MemAvailable: {32 * GIB // 1024} kB\n")
    controller = tmp_path / "memory"
    controller.mkdir()
    (controller / "memory.limit_in_bytes").write_text(str(10 * GIB))
    (controller / "memory.usage_in_bytes").write_text(str(9 * GIB))
    # WHY: emulate the older NAS cgroup controller and host procfs using actual files.
    monkeypatch.setattr(memory_budget.platform, "system", lambda: "Linux")
    monkeypatch.setattr(memory_budget, "_MEMINFO_PATH", meminfo)
    monkeypatch.setattr(memory_budget, "_CGROUP", tmp_path)

    shortfall = memory_budget.memory_shortfall("acestep-v15-turbo", None)

    assert shortfall is not None
    assert shortfall.available_bytes == GIB


def test_an_unbounded_v1_controller_is_not_available_memory(tmp_path, monkeypatch):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal: 1000 kB\n")
    controller = tmp_path / "memory"
    controller.mkdir()
    (controller / "memory.limit_in_bytes").write_text(str(2**63 - 4096))
    (controller / "memory.usage_in_bytes").write_text("1024")
    # WHY: old controllers use a huge numeric sentinel; procfs may omit MemAvailable.
    monkeypatch.setattr(memory_budget.platform, "system", lambda: "Linux")
    monkeypatch.setattr(memory_budget, "_MEMINFO_PATH", meminfo)
    monkeypatch.setattr(memory_budget, "_CGROUP", tmp_path)

    assert memory_budget.available_memory_bytes() is None


def test_missing_or_unlimited_v2_limits_preserve_host_budget(tmp_path, monkeypatch):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(f"MemAvailable: {4 * GIB // 1024} kB\n")
    # WHY: isolate procfs and the controller mount; neither requires mocking budget math.
    monkeypatch.setattr(memory_budget.platform, "system", lambda: "Linux")
    monkeypatch.setattr(memory_budget, "_MEMINFO_PATH", meminfo)
    monkeypatch.setattr(memory_budget, "_CGROUP", tmp_path)
    assert memory_budget.available_memory_bytes() == 4 * GIB
    (tmp_path / "memory.max").write_text("max\n")
    (tmp_path / "memory.current").write_text(str(GIB))
    assert memory_budget.available_memory_bytes() == 4 * GIB


def test_host_pressure_wins_and_an_over_limit_container_has_no_room(tmp_path, monkeypatch):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(f"MemAvailable: {2 * GIB // 1024} kB\n")
    (tmp_path / "memory.max").write_text(str(10 * GIB))
    (tmp_path / "memory.current").write_text(str(GIB))
    # WHY: exercise pressure from either independently measured filesystem boundary.
    monkeypatch.setattr(memory_budget.platform, "system", lambda: "Linux")
    monkeypatch.setattr(memory_budget, "_MEMINFO_PATH", meminfo)
    monkeypatch.setattr(memory_budget, "_CGROUP", tmp_path)
    assert memory_budget.available_memory_bytes() == 2 * GIB
    (tmp_path / "memory.current").write_text(str(11 * GIB))
    shortfall = memory_budget.memory_shortfall("acestep-v15-turbo", None)
    assert shortfall is not None
    assert shortfall.available_bytes == 0


def test_a_readable_container_budget_still_applies_without_host_procfs(tmp_path, monkeypatch):
    (tmp_path / "memory.max").write_text(str(10 * GIB))
    (tmp_path / "memory.current").write_text(str(9 * GIB))
    # WHY: a sandbox may hide host procfs while exposing its own controller counters.
    monkeypatch.setattr(memory_budget.platform, "system", lambda: "Linux")
    monkeypatch.setattr(memory_budget, "_MEMINFO_PATH", tmp_path / "absent")
    monkeypatch.setattr(memory_budget, "_CGROUP", tmp_path)

    shortfall = memory_budget.memory_shortfall("acestep-v15-turbo", None)

    assert shortfall is not None
    assert shortfall.available_bytes == GIB


def test_host_namespace_membership_uses_its_nested_limit(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    (proc / "self").mkdir(parents=True)
    (proc / "meminfo").write_text(f"MemAvailable: {32 * GIB // 1024} kB\n")
    root = tmp_path / "cgroup"
    group = root / "workload"
    group.mkdir(parents=True)
    (root / "memory.max").write_text(str(64 * GIB))
    (root / "memory.current").write_text("0")
    (group / "memory.max").write_text(str(10 * GIB))
    (group / "memory.current").write_text(str(9 * GIB))
    (proc / "self/cgroup").write_text("0::/workload\n")
    (proc / "self/mountinfo").write_text(f"31 22 0:28 / {root} rw - cgroup2 cgroup rw\n")
    # WHY: emulate kernel membership, mount mapping and host counters as real files.
    monkeypatch.setattr(memory_budget.platform, "system", lambda: "Linux")
    monkeypatch.setattr(memory_budget, "_MEMINFO_PATH", proc / "meminfo")
    monkeypatch.setattr(memory_budget, "_CGROUP", root)
    monkeypatch.setattr(memory_budget, "_PROC_ROOT", proc, raising=False)

    shortfall = memory_budget.memory_shortfall("acestep-v15-turbo", None)

    assert shortfall is not None
    assert shortfall.available_bytes == GIB


def test_a_tighter_parent_limits_the_childs_remaining_memory(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    (proc / "self").mkdir(parents=True)
    (proc / "meminfo").write_text(f"MemAvailable: {32 * GIB // 1024} kB\n")
    root = tmp_path / "cgroup"
    parent = root / "parent"
    child = parent / "worker"
    child.mkdir(parents=True)
    (parent / "memory.max").write_text(str(8 * GIB))
    (parent / "memory.current").write_text(str(7 * GIB))
    (child / "memory.max").write_text(str(10 * GIB))
    (child / "memory.current").write_text(str(GIB))
    (proc / "self/cgroup").write_text("0::/parent/worker\n")
    (proc / "self/mountinfo").write_text(f"31 22 0:28 / {root} rw - cgroup2 cgroup rw\n")
    # WHY: the kernel enforces finite parent limits across sibling workloads too.
    monkeypatch.setattr(memory_budget.platform, "system", lambda: "Linux")
    monkeypatch.setattr(memory_budget, "_MEMINFO_PATH", proc / "meminfo")
    monkeypatch.setattr(memory_budget, "_CGROUP", root)
    monkeypatch.setattr(memory_budget, "_PROC_ROOT", proc)

    shortfall = memory_budget.memory_shortfall("acestep-v15-turbo", None)

    assert shortfall is not None
    assert shortfall.available_bytes == GIB


@pytest.mark.parametrize("membership", ["/worker", "/docker/container/worker"])
def test_mounted_subtrees_map_private_and_host_membership(tmp_path, monkeypatch, membership):
    proc = tmp_path / "proc"
    (proc / "self").mkdir(parents=True)
    (proc / "meminfo").write_text(f"MemAvailable: {32 * GIB // 1024} kB\n")
    root = tmp_path / "cgroup"
    child = root / "worker"
    child.mkdir(parents=True)
    (child / "memory.max").write_text(str(10 * GIB))
    (child / "memory.current").write_text(str(9 * GIB))
    (proc / "self/cgroup").write_text(f"0::{membership}\n")
    (proc / "self/mountinfo").write_text(
        f"31 22 0:28 /docker/container {root} rw - cgroup2 cgroup rw\n"
    )
    # WHY: cgroup namespaces report relative paths while mount roots may retain host paths.
    monkeypatch.setattr(memory_budget.platform, "system", lambda: "Linux")
    monkeypatch.setattr(memory_budget, "_MEMINFO_PATH", proc / "meminfo")
    monkeypatch.setattr(memory_budget, "_CGROUP", root)
    monkeypatch.setattr(memory_budget, "_PROC_ROOT", proc)

    assert memory_budget.available_memory_bytes() == GIB


def test_v1_membership_uses_the_memory_controller_mount(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    (proc / "self").mkdir(parents=True)
    (proc / "meminfo").write_text(f"MemAvailable: {32 * GIB // 1024} kB\n")
    root = tmp_path / "cgroup"
    controller = root / "memory"
    child = controller / "worker"
    child.mkdir(parents=True)
    (child / "memory.limit_in_bytes").write_text(str(10 * GIB))
    (child / "memory.usage_in_bytes").write_text(str(9 * GIB))
    (proc / "self/cgroup").write_text("3:cpu:/ignored\n5:memory:/worker\n")
    (proc / "self/mountinfo").write_text(
        f"31 22 0:28 / {controller} rw - cgroup cgroup rw,memory\n"
    )
    # WHY: v1 assigns each controller its own membership and mount point.
    monkeypatch.setattr(memory_budget.platform, "system", lambda: "Linux")
    monkeypatch.setattr(memory_budget, "_MEMINFO_PATH", proc / "meminfo")
    monkeypatch.setattr(memory_budget, "_CGROUP", root)
    monkeypatch.setattr(memory_budget, "_PROC_ROOT", proc)

    assert memory_budget.available_memory_bytes() == GIB


def test_clean_inactive_weight_pages_are_reclaimable_before_loading(tmp_path, monkeypatch):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(f"MemAvailable: {32 * GIB // 1024} kB\n")
    (tmp_path / "memory.max").write_text(str(10 * GIB))
    (tmp_path / "memory.current").write_text(str(7 * GIB))
    (tmp_path / "memory.stat").write_text(
        f"file {6 * GIB}\ninactive_file {4 * GIB}\n"
        "shmem 0\nfile_mapped 0\nfile_dirty 0\nfile_writeback 0\nunevictable 0\n"
    )
    # WHY: real cgroup files distinguish cached weights from anonymous model allocations.
    monkeypatch.setattr(memory_budget.platform, "system", lambda: "Linux")
    monkeypatch.setattr(memory_budget, "_MEMINFO_PATH", meminfo)
    monkeypatch.setattr(memory_budget, "_CGROUP", tmp_path)

    assert memory_budget.memory_shortfall("acestep-v15-turbo", None) is None


@pytest.mark.parametrize(
    "protected", ["shmem", "file_mapped", "file_dirty", "file_writeback", "unevictable"]
)
def test_shared_mapped_dirty_or_pinned_pages_cannot_be_credited(tmp_path, monkeypatch, protected):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(f"MemAvailable: {32 * GIB // 1024} kB\n")
    (tmp_path / "memory.max").write_text(str(10 * GIB))
    (tmp_path / "memory.current").write_text(str(7 * GIB))
    counters = {
        "file": 6 * GIB,
        "inactive_file": 4 * GIB,
        "shmem": 0,
        "file_mapped": 0,
        "file_dirty": 0,
        "file_writeback": 0,
        "unevictable": 0,
    }
    counters[protected] = 4 * GIB
    (tmp_path / "memory.stat").write_text(
        "".join(f"{key} {value}\n" for key, value in counters.items())
    )
    # WHY: inactive file counters alone do not prove that backing pages can be reclaimed.
    monkeypatch.setattr(memory_budget.platform, "system", lambda: "Linux")
    monkeypatch.setattr(memory_budget, "_MEMINFO_PATH", meminfo)
    monkeypatch.setattr(memory_budget, "_CGROUP", tmp_path)

    shortfall = memory_budget.memory_shortfall("acestep-v15-turbo", None)
    assert shortfall is not None
    assert shortfall.available_bytes == 5 * GIB


def test_racing_cache_counters_never_exceed_the_container_limit(tmp_path, monkeypatch):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(f"MemAvailable: {32 * GIB // 1024} kB\n")
    (tmp_path / "memory.max").write_text(str(10 * GIB))
    (tmp_path / "memory.current").write_text(str(GIB))
    (tmp_path / "memory.stat").write_text(
        f"file {6 * GIB}\ninactive_file {4 * GIB}\n"
        "shmem 0\nfile_mapped 0\nfile_dirty 0\nfile_writeback 0\nunevictable 0\n"
    )
    # WHY: stat and current are separate kernel reads and may straddle a model release.
    monkeypatch.setattr(memory_budget.platform, "system", lambda: "Linux")
    monkeypatch.setattr(memory_budget, "_MEMINFO_PATH", meminfo)
    monkeypatch.setattr(memory_budget, "_CGROUP", tmp_path)

    assert memory_budget.available_memory_bytes() == 10 * GIB
