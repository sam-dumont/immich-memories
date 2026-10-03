"""A requested GPU tier is distinct from a proven inference GPU."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from immich_memories.config_loader import Config
from immich_memories.preflight import CheckStatus
from immich_memories.preflight_compute import check_inference_compute


@pytest.mark.parametrize(
    "provider,status,fallback,expected",
    [
        ("CPUExecutionProvider", 200, True, CheckStatus.WARNING),
        ("CUDAExecutionProvider", 200, True, CheckStatus.OK),
        (None, 503, True, CheckStatus.WARNING),
        (None, 503, False, CheckStatus.ERROR),
    ],
)
def test_preflight_reports_service_compute_without_downgrading_requested_tier(
    monkeypatch, provider, status, fallback, expected
):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — the stdlib handler interface
            assert self.path == "/health"
            self.send_response(status)
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "provider": provider}).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # WHY: this test host may have Metal/CUDA; the fixture describes a CPU-only app host.
    monkeypatch.setattr(
        "immich_memories.config_compute.local_inference_acceleration",
        lambda: (False, "No local GPU"),
    )
    config = Config(
        tier="gpu",
        inference={
            "facts_base_url": f"http://127.0.0.1:{server.server_port}",
            "fallback_to_local": fallback,
        },
    )
    try:
        result = check_inference_compute(config)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert result.status is expected
    assert config.tier == "gpu"
    if provider == "CPUExecutionProvider":
        assert "CPUExecutionProvider" in result.details


@pytest.mark.parametrize("tier", ["basic", "nas"])
def test_basic_does_not_probe_an_inference_service(tier):
    config = Config(tier=tier, inference={"facts_base_url": "https://never-contact.example"})
    result = check_inference_compute(config)
    assert result.status is CheckStatus.SKIPPED
