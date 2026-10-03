"""Caption preflight waits for a cold model within the configured request budget."""

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from immich_memories.analysis.editorial_description_contract import API_MODEL
from immich_memories.config import Config
from immich_memories.preflight import CheckStatus, check_caption_endpoint


@contextmanager
def delayed_caption_server(delay: float) -> Iterator[str]:
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 — HTTP server callback
            release.wait(delay)
            body = json.dumps({"data": [{"id": API_MODEL}]}).encode()
            try:
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # A timed-out client has already closed its socket.

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


def test_cold_caption_server_can_take_longer_than_five_seconds() -> None:
    with delayed_caption_server(5.5) as base_url:
        config = Config(tier="gpu", editorial={"preparation": {"caption_base_url": base_url}})
        result = check_caption_endpoint(config)

    assert result.status is CheckStatus.OK


def test_caption_readiness_honors_its_configured_timeout() -> None:
    with delayed_caption_server(0.3) as base_url:
        config = Config(
            tier="gpu",
            editorial={
                "preparation": {"caption_base_url": base_url, "caption_timeout_seconds": 0.05}
            },
        )
        result = check_caption_endpoint(config)

    assert result.status is CheckStatus.ERROR
    assert "slow to answer" in result.message.lower()
    assert "caption_timeout_seconds" in (result.details or "")
