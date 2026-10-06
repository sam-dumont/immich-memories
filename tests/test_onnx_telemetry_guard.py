"""ONNX Runtime telemetry stays off: every session opens through one helper (#2181)."""

from __future__ import annotations

import re
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
