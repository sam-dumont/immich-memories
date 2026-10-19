"""Session options size the thread pool to the process and keep idle threads asleep."""

from types import SimpleNamespace

import pytest

from immich_memories import onnx_session

SPINNING = ("session.intra_op.allow_spinning", "session.inter_op.allow_spinning")


class _Options:
    """The slice of ``onnxruntime.SessionOptions`` these options touch."""

    def __init__(self):
        self.entries: dict[str, str] = {}
        self.intra_op_num_threads = 0
        self.inter_op_num_threads = 0
        self.graph_optimization_level = None

    def add_session_config_entry(self, key, value):
        self.entries[key] = value

    def get_session_config_entry(self, key):
        return self.entries[key]


# WHY: the unit environment need not have the onnxruntime wheel; this is its options API.
_FAKE_ORT = SimpleNamespace(
    SessionOptions=_Options, GraphOptimizationLevel=SimpleNamespace(ORT_ENABLE_ALL="all")
)


def test_idle_inference_threads_sleep_instead_of_spinning():
    options = onnx_session.cpu_bounded_options(_FAKE_ORT)

    assert [options.get_session_config_entry(key) for key in SPINNING] == ["0", "0"]


@pytest.mark.parametrize(("cpus", "threads"), [(1, 1), (4, 3), (32, 8)])
def test_the_pool_leaves_one_cpu_free_and_stops_at_eight(monkeypatch, cpus, threads):
    # WHY: the CPU count is the host boundary (affinity and cgroup quota).
    monkeypatch.setattr(onnx_session, "available_cpus", lambda: cpus)

    assert onnx_session.inference_threads() == threads
    assert onnx_session.cpu_bounded_options(_FAKE_ORT).intra_op_num_threads == threads


def test_the_real_runtime_accepts_the_spinning_switches():
    ort = pytest.importorskip("onnxruntime")

    options = onnx_session.cpu_bounded_options(ort)

    assert [options.get_session_config_entry(key) for key in SPINNING] == ["0", "0"]
