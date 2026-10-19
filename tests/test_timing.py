"""Run timing keeps concurrent parentage and failed work, without touching a store."""

import logging

import pytest

from immich_memories.tracking import timing


def test_failed_span_keeps_parent_warning_and_elapsed_time():
    moments = iter([10.0, 11.0, 13.0, 15.0])
    with (
        timing.collecting(now=lambda: next(moments)) as collected,
        pytest.raises(ValueError, match="broken"),
        timing.span("selection"),
        timing.span("selection.reader", items=2),
    ):
        logging.getLogger("immich_memories.reader").warning("retry exhausted")
        raise ValueError("broken")

    child, parent = collected.spans
    assert child.parent_id == parent.span_id
    assert child.duration == 2.0
    assert child.items == 2
    assert child.error["type"] == "ValueError"
    assert child.warnings == ["retry exhausted"]
    assert parent.duration == 5.0
    assert timing.active() is None


def test_preparation_costs_read_the_measured_spans():
    from immich_memories.analysis.preparation.report import ProducerClock

    moments = iter([1.0, 5.0])
    with timing.collecting(now=lambda: next(moments)) as collected:
        clock = ProducerClock(spans=collected.spans)
        with timing.span("preparation.detectors", items=8):
            clock.report("detectors", 16, 16)
    (cost,) = clock.costs()
    assert cost.producer == "detectors"
    assert cost.pending == 16
    assert cost.seconds_per_picture(8) == 0.5


def test_secrets_are_removed_before_buffering_logs_and_failures():
    import secrets

    from immich_memories.logging_config import install_secret_redaction

    secret = secrets.token_urlsafe(24)
    install_secret_redaction([secret])
    with timing.collecting() as collected, pytest.raises(ValueError), timing.span("reader"):
        logging.getLogger("immich_memories.reader").warning("request failed: %s", secret)
        raise ValueError(f"request failed: {secret}")

    assert secret not in str(collected.logs)
    assert secret not in str(collected.spans[0].to_dict())


def test_concurrent_runs_keep_their_own_warnings_and_parentage():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    ready = Barrier(2)

    def run(name):
        with timing.collecting() as collected, timing.span(name):
            ready.wait(timeout=10)
            with timing.span("reader"):
                logging.getLogger("immich_memories.reader").warning(name)
        return collected

    with ThreadPoolExecutor(max_workers=2) as workers:
        left, right = list(workers.map(run, ("left", "right")))
    assert left.logs == ["left"]
    assert right.logs == ["right"]
    for collected in (left, right):
        child, parent = collected.spans
        assert child.parent_id == parent.span_id
        assert child.warnings == [parent.name]


@pytest.mark.parametrize(("code", "status"), [(0, "completed"), (None, "completed"), (2, "failed")])
def test_an_exit_ends_the_run_by_its_status_code(code, status):
    import sys

    from immich_memories.db import open_store
    from immich_memories.tracking.run_observations import observe_run

    with (
        pytest.raises(SystemExit),
        observe_run(open_store(), source="manual", capture_system=False) as tracker,
    ):
        sys.exit(code)
    saved = tracker.db.get_run(tracker.run_id)
    assert saved.status == status
    run_span = next(span for span in _spans(tracker) if span.name == "run")
    assert (run_span.error is None) == (status == "completed")


def _spans(tracker):
    from immich_memories.tracking.span_store import SpanStore

    return SpanStore(tracker.db.store).load(tracker.run_id).spans


def test_run_logs_keep_the_last_lines_and_count_every_level(monkeypatch):
    # WHY: a small cap stands in for the real one without logging thousands of lines.
    monkeypatch.setattr(timing, "LOG_LINES", 10)
    log = logging.getLogger("immich_memories.fixture")
    with timing.collecting() as collected:
        for number in range(25):
            log.warning("line %d", number)
        log.error("last")
    assert len(collected.logs) == 10
    assert collected.logs[-1].endswith("last")
    assert collected.diagnostics["log_counts"] == {"WARNING": 25, "ERROR": 1}


def test_a_run_opened_after_imports_names_that_time_startup():
    import time

    from immich_memories.db import open_store
    from immich_memories.process_start import Startup
    from immich_memories.tracking.run_observations import observe_run
    from immich_memories.tracking.span_progress import uncovered_seconds

    startup = Startup(time.perf_counter() - 4.0)
    with observe_run(open_store(), source="manual", capture_system=False, startup=startup) as run:
        pass
    spans = {span.name: span for span in _spans(run)}
    assert spans["startup"].duration >= 4.0
    assert spans["startup"].parent_id == spans["run"].span_id
    assert spans["run"].duration >= spans["startup"].duration
    assert uncovered_seconds(list(spans.values()), 0.0) < 0.5


def test_only_the_first_cli_run_of_a_process_claims_its_startup(monkeypatch):
    import time

    import click
    from click.testing import CliRunner

    from immich_memories import process_start
    from immich_memories.config.loader import Config
    from immich_memories.tracking.run_observations import current_tracker, observed_command

    # WHY: this test process began long before; a fresh mark stands in for a CLI that just did.
    fresh = process_start.Startup(time.perf_counter() - 2.0)
    monkeypatch.setattr(process_start, "_process", fresh)
    monkeypatch.setattr(process_start, "_unclaimed", [fresh])
    runs = []

    @click.command()
    @click.pass_context
    @observed_command("manual")
    def command(ctx):
        runs.append(current_tracker())

    for _ in range(2):
        result = CliRunner().invoke(command, obj={"config": Config()}, catch_exceptions=False)
        assert result.exit_code == 0
    first, second = ({span.name for span in _spans(run)} for run in runs)
    assert "startup" in first
    assert "startup" not in second


def test_a_cold_start_is_split_into_named_phases_that_sum_to_it():
    from immich_memories.process_start import Startup

    cold = Startup(started=0.0, marks=[("imports", 2.0), ("config", 3.5), ("system", 9.0)])
    with timing.collecting(now=lambda: 30.0) as collected, timing.span("run") as root:
        timing.open_at(root, cold)

    startup = next(span for span in collected.spans if span.name == "startup")
    children = [span for span in collected.spans if span.parent_id == startup.span_id]
    assert [(span.name, span.start, span.duration) for span in children] == [
        ("startup.imports", 0.0, 2.0),
        ("startup.config", 2.0, 1.5),
        ("startup.system", 3.5, 5.5),
        ("startup.run_record", 9.0, 21.0),
    ]
    assert startup.duration == 30.0


def test_a_span_records_a_peak_at_least_what_it_allocated():
    import subprocess
    import sys

    # Keep earlier tests' allocations and background work out of this RSS measurement.
    script = f"import runpy; runpy.run_path({__file__!r})['_check_live_memory_peaks']()"
    subprocess.run([sys.executable, "-c", script], check=True, timeout=30)


def _tree_floor(child_size: int) -> int:
    import os

    from immich_memories.tracking import peak_memory

    return (peak_memory.rss_bytes(os.getpid()) or 0) + child_size


def _check_live_memory_peaks():
    import os
    import subprocess
    import sys
    import time

    from immich_memories.tracking import peak_memory

    size = 64 * 1024 * 1024
    # Random bytes keep macOS compression from shrinking the resident allocation, and
    # touching a byte per page until stdin closes keeps a loaded runner from paging it out.
    child = (
        "import os, select, sys\n"
        f"held = os.urandom({size})\n"
        "print('ready', flush=True)\n"
        "while not select.select([sys.stdin], [], [], 0.05)[0]:\n"
        "    bytes(held[::4096])\n"
    )
    with timing.collecting() as collected, timing.span("run"):
        with timing.span("download"):
            held = os.urandom(size)
        del held
        with subprocess.Popen(
            [sys.executable, "-c", child], stdin=subprocess.PIPE, stdout=subprocess.PIPE
        ) as ffmpeg:
            try:
                assert ffmpeg.stdout.readline() == b"ready\n"
                with timing.span("assembly"):
                    observed = peak_memory.watch_open()
                    try:
                        # The floor follows this process's RSS as it is now: macOS keeps the
                        # freed download's pages cached as resident and reclaims them only
                        # under pressure, so the RSS at open can drop by `size` mid-wait.
                        deadline = time.monotonic() + 10
                        minimum_tree = _tree_floor(size)
                        while observed.tree < minimum_tree and time.monotonic() < deadline:
                            time.sleep(0.01)
                            minimum_tree = _tree_floor(size)
                        assert observed.tree >= minimum_tree, (observed.tree, minimum_tree)
                    finally:
                        peak_memory.watch_close(observed)
            finally:
                ffmpeg.communicate(b"", timeout=5)

    download, assembly, run = collected.spans
    assert download.peak_rss >= size
    assert download.peak_tree_rss >= download.peak_rss
    assert assembly.peak_tree_rss >= minimum_tree
    assert run.peak_rss >= download.peak_rss


def test_spans_outside_a_run_measure_no_memory():
    with timing.span("loose") as measured:
        pass
    assert measured.peak_rss is None


def test_a_parent_span_reports_at_least_its_childs_peak(monkeypatch):
    from immich_memories.tracking import peak_memory

    resident = {"bytes": 10**14}
    # WHY: RSS is read from the OS; a scripted reading makes the child's high point
    # one that only the child's own close sees, which real sampling hits by chance.
    monkeypatch.setattr(peak_memory, "rss_bytes", lambda _pid: resident["bytes"])
    monkeypatch.setattr(peak_memory, "SAMPLE_SECONDS", 3600.0)
    with timing.collecting() as collected, timing.span("run"):
        with timing.span("download"):
            resident["bytes"] = 10**15
        resident["bytes"] = 10**14

    download, run = collected.spans
    assert download.peak_rss == 10**15
    assert run.peak_rss >= download.peak_rss
    assert run.peak_tree_rss >= download.peak_tree_rss


def _fake_proc(root, threads: int, spawners: dict[int, list[int]]) -> None:
    import os

    pid = os.getpid()
    task = root / str(pid) / "task"
    for tid in range(pid, pid + threads):
        (task / str(tid)).mkdir(parents=True)
        kids = spawners.get(tid - pid, [])
        (task / str(tid) / "children").write_text(" ".join(map(str, kids)))
    (root / str(pid) / "statm").write_text("10 100 0 0 0 0 0")
    for kid in {k for ks in spawners.values() for k in ks}:
        (root / str(kid) / "task" / str(kid)).mkdir(parents=True)
        (root / str(kid) / "task" / str(kid) / "children").write_text("")
        (root / str(kid) / "statm").write_text("10 50 0 0 0 0 0")


def test_linux_tick_reads_few_files_with_many_threads(tmp_path, monkeypatch):
    import os

    from immich_memories.tracking import peak_memory

    # WHY: a fake /proc, so the read count is deterministic on any OS.
    _fake_proc(tmp_path, threads=100, spawners={0: [900001], 40: [900002], 41: [900003]})
    monkeypatch.setattr(peak_memory, "_PROC", tmp_path)
    monkeypatch.setattr(peak_memory, "_LIBPROC", None)
    monkeypatch.setattr(peak_memory, "_PAGE", 4096)
    reads: list[str] = []
    real = peak_memory._read
    monkeypatch.setattr(peak_memory, "_read", lambda p: (reads.append(p.name), real(p))[1])

    walker = peak_memory._ThreadChildren()
    totals = [peak_memory.tree_rss_bytes(os.getpid(), walker) for _ in range(5)]

    own, kid = 100 * 4096, 50 * 4096
    assert totals == [own + 3 * kid] * 5  # every child seen on every tick
    # Before: ~100 children reads per tick. Now one full walk, then a handful.
    assert reads.count("children") <= 100 + 3 + 4 * 8


def test_linux_walk_survives_missing_and_garbled_proc_files(tmp_path, monkeypatch):
    import os

    from immich_memories.tracking import peak_memory

    pid = os.getpid()
    # WHY: a fake /proc, so the error paths are reachable on any OS.
    _fake_proc(tmp_path, threads=3, spawners={0: [900001]})
    (tmp_path / str(pid) / "task" / str(pid + 1) / "children").unlink()
    (tmp_path / str(pid) / "task" / str(pid + 2) / "children").write_text("not-a-pid")
    (tmp_path / "900001" / "task" / "900001" / "children").write_text("junk")
    monkeypatch.setattr(peak_memory, "_PROC", tmp_path)
    monkeypatch.setattr(peak_memory, "_LIBPROC", None)
    monkeypatch.setattr(peak_memory, "_PAGE", 4096)

    # The child's own children file is garbled; it still counts, with no grandchildren.
    assert peak_memory.tree_rss_bytes(pid) == (100 + 50) * 4096
    (tmp_path / "900001" / "task" / "900001" / "children").unlink()
    assert peak_memory.tree_rss_bytes(pid) == (100 + 50) * 4096

    import shutil

    shutil.rmtree(tmp_path / str(pid) / "task")
    assert peak_memory._ThreadChildren().children(pid) == []


def test_thread_children_remembers_a_spawning_thread_between_full_walks(tmp_path, monkeypatch):
    import os

    from immich_memories.tracking import peak_memory

    pid = os.getpid()
    # WHY: a fake /proc, so thread contents are controlled.
    _fake_proc(tmp_path, threads=10, spawners={})
    monkeypatch.setattr(peak_memory, "_PROC", tmp_path)
    walker = peak_memory._ThreadChildren()
    side = tmp_path / str(pid) / "task" / str(pid + 7) / "children"

    assert walker.children(pid) == []
    side.write_text("900009")  # a side thread starts a process after the full walk
    assert walker.children(pid) == []  # not seen until the next full walk
    for _ in range(peak_memory.FULL_WALK_EVERY - 2):
        walker.children(pid)
    assert walker.children(pid) == [900009]  # full walk finds it
    assert walker.children(pid) == [900009]  # then it is read on light ticks too


def test_macos_libproc_children_reach_grandchildren(tmp_path, monkeypatch):
    from immich_memories.tracking import peak_memory

    tree = {1000: [2000], 2000: [3000], 3000: []}

    class FakeLibproc:
        # WHY: libproc is macOS-only; this stands in for proc_listchildpids.
        def proc_listchildpids(self, pid, buffer, _size):
            for slot, child in enumerate(tree.get(pid, [])):
                buffer[slot] = child
            return len(tree.get(pid, []))

    monkeypatch.setattr(peak_memory, "_LIBPROC", FakeLibproc())
    monkeypatch.setattr(peak_memory, "rss_bytes", lambda pid: pid)

    assert peak_memory.tree_rss_bytes(1000) == 1000 + 2000 + 3000
