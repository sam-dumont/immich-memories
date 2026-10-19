"""The one place an ONNX Runtime session is opened."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from immich_memories.processing.memory_budget import available_cpus


def open_inference_session(
    ort: Any, model_path: Path | str, *, providers: list[str], options: Any = None
) -> Any:
    """Open a session with ONNX Runtime's built-in telemetry switched off first.

    ONNX Runtime ships Microsoft telemetry on: it sends HTTP by default, and its
    shutdown can abort the process (#2181). The switch has to be flipped before
    the first session exists, so every session in the app and the inference
    service is opened through here (``tests/test_onnx_telemetry_guard.py``).
    """
    ort.disable_telemetry_events()
    if options is None:
        return ort.InferenceSession(str(model_path), providers=providers)
    return ort.InferenceSession(str(model_path), sess_options=options, providers=providers)


def cpu_bounded_options(ort: Any) -> Any:
    """Session options whose thread pool fits the CPUs this process may use.

    ONNX Runtime sizes its pool from the host's cores; in a container the CPU limit (cgroup
    cpu.max) is what the process can use, and a larger pool only queues on it.
    """
    options = ort.SessionOptions()
    options.intra_op_num_threads = max(1, min(8, available_cpus() - 1))
    options.inter_op_num_threads = 1
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return options
