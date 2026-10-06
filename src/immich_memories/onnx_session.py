"""The one place an ONNX Runtime session is opened."""

from __future__ import annotations

from pathlib import Path
from typing import Any


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
