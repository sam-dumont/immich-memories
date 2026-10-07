"""ONNX Runtime telemetry stays off: every session opens through one helper (#2181)."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from immich_memories.onnx_session import open_inference_session

REPO = Path(__file__).resolve().parents[1]
# The helper, and the detector worker that cannot import it (it runs in an interpreter
# without immich_memories), which carries its own disabling call.
OPENERS = ("onnx_session.py", "editorial_preparation_detectors.py")


def test_telemetry_is_disabled_before_the_session_is_constructed():
    calls: list[str] = []
    # WHY: ONNX Runtime is the external boundary; a spy records the order of its calls.
    ort = SimpleNamespace(
        disable_telemetry_events=lambda: calls.append("disable"),
        InferenceSession=lambda *_a, **_kw: calls.append("session") or "session",
    )

    session = open_inference_session(ort, "model.onnx", providers=["CPUExecutionProvider"])

    assert session == "session"
    assert calls == ["disable", "session"]


def test_no_module_opens_an_inference_session_without_the_helper():
    offenders = [
        str(path.relative_to(REPO))
        for root in ("src", "services")
        for path in (REPO / root).rglob("*.py")
        if path.name not in OPENERS
        and re.search(r"\bInferenceSession\(", path.read_text(encoding="utf-8"))
    ]

    assert offenders == []


def test_the_files_that_open_sessions_themselves_disable_telemetry_first():
    for path in (REPO / "src").rglob("*.py"):
        if path.name in OPENERS:
            text = path.read_text(encoding="utf-8")
            assert text.index("disable_telemetry_events()") < text.index("InferenceSession(")


def test_importing_the_cli_switches_the_runtime_telemetry_off_process_wide():
    # ONNX Runtime 1.30 on macOS starts its Microsoft telemetry worker when the first
    # environment is created and uploads from a thread that outlives the call to
    # disable_telemetry_events(), so the switch has to be in the environment before
    # any library can load the runtime (#2217).
    probe = (
        "import os, sys; os.environ.pop('ORT_DISABLE_TELEMETRY', None)\n"
        "import immich_memories.cli\n"
        "print(os.environ.get('ORT_DISABLE_TELEMETRY'), 'onnxruntime' in sys.modules)"
    )

    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )

    assert result.stdout.split()[0] == "1"


def test_the_detector_worker_inherits_the_telemetry_switch():
    from immich_memories.analysis.editorial_preparation_detectors import _worker_env

    assert _worker_env("", allow_downloads=False)["ORT_DISABLE_TELEMETRY"] == "1"
