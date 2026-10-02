"""Reader preflight distinguishes a slow response body from a failed connection."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from pydantic import ValidationError

from immich_memories.config import Config
from immich_memories.config_models_llm import LLMConfig
from immich_memories.preflight import CheckStatus, check_llm


@contextmanager
def slow_reader(*, catalogue: bool = True) -> Iterator[str]:
    """An HTTP peer that sends its headers immediately and delays its body."""
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 — HTTP server callback
            if not catalogue:
                self.send_error(404)
                return
            body = {"data": [{"id": "fixture-reader"}], "models": [{"name": "fixture-reader"}]}
            self.respond(body)

        def do_POST(self) -> None:  # noqa: N802 — HTTP server callback
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.respond({"choices": [{"message": {"content": "hi"}}]})

        def respond(self, payload: dict) -> None:
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.flush()
            release.wait(0.3)
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # The preflight deadline legitimately closed the client socket.

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize(
    "provider", ["openai-compatible", "ollama", "anthropic", "anthropic-probe"]
)
def test_preflight_honors_reader_timeout_and_names_a_slow_body(provider: str) -> None:
    with slow_reader(catalogue=provider != "anthropic-probe") as base_url:
        config = Config(
            llm={
                "enabled": True,
                "provider": provider.removesuffix("-probe"),
                "base_url": base_url,
                "model": "fixture-reader",
                "preflight_timeout_seconds": 0.05,
            }
        )
        result = check_llm(config)

    assert result.status is CheckStatus.WARNING
    assert "slow to answer" in result.message.lower()
    assert "preflight_timeout_seconds" in (result.details or "")


@pytest.mark.parametrize(
    "provider", ["openai-compatible", "ollama", "anthropic", "anthropic-probe"]
)
def test_increasing_preflight_timeout_allows_the_busy_reader_to_answer(provider: str) -> None:
    with slow_reader(catalogue=provider != "anthropic-probe") as base_url:
        config = Config(
            llm={
                "enabled": True,
                "provider": provider.removesuffix("-probe"),
                "base_url": base_url,
                "model": "fixture-reader",
                "preflight_timeout_seconds": 2,
            }
        )
        result = check_llm(config)

    assert result.status is CheckStatus.OK
    assert result.message.startswith("Connected")


def test_closed_reader_port_is_a_connection_failure_not_a_slow_answer() -> None:
    with slow_reader() as base_url:
        config = Config(llm={"enabled": True, "base_url": base_url, "model": "fixture-reader"})
    result = check_llm(config)

    assert result.status is CheckStatus.WARNING
    assert result.message == "Cannot connect"


@pytest.mark.parametrize("timeout", [0, -1, 3601, float("inf"), float("nan")])
def test_preflight_timeout_rejects_unbounded_or_nonpositive_values(timeout: float) -> None:
    with pytest.raises(ValidationError):
        LLMConfig(preflight_timeout_seconds=timeout)


def test_preflight_timeout_defaults_to_ten_seconds_independently_of_generation() -> None:
    config = LLMConfig(timeout_seconds=600)
    assert config.preflight_timeout_seconds == 10
