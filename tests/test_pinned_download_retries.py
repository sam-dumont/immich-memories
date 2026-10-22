"""A pinned download rides out a temporary server error and still fails on a real one."""

from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.error import HTTPError

import httpx
import pytest

from immich_memories import pinned_models
from immich_memories.pinned_models import fetch_pinned_model
from immich_memories.titles import script_fonts

_BODY = b"synthetic pinned artifact"


@pytest.fixture
def flaky_host():
    """A loopback host that answers the given statuses in turn, then serves the file."""
    answers: list[int] = []
    requests: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 -- stdlib server interface
            requests.append(self.path)
            status = answers.pop(0) if answers else 200
            self.send_response(status)
            body = _BODY if status == 200 else b"busy"
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/artifact", answers, requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture(params=["model", "font"])
def download(request, monkeypatch, tmp_path):
    destination = tmp_path / "artifact"
    digest = hashlib.sha256(_BODY).hexdigest()
    # WHY: skip the real backoff waits; the retry decisions stay real.
    monkeypatch.setattr(pinned_models, "_RETRY_DELAYS", (0.0, 0.0, 0.0))
    monkeypatch.setattr(script_fonts, "_RETRY_DELAYS", (0.0, 0.0, 0.0))

    def fetch(url):
        if request.param == "model":
            fetch_pinned_model(url=url, destination=destination, sha256=digest)
        else:
            font = script_fonts.ScriptFont("artifact", digest, len(_BODY))
            # WHY: one synthetic pin on a loopback source; fetching and verification stay real.
            monkeypatch.setattr(script_fonts, "SCRIPT_FONTS", (font,))
            monkeypatch.setattr(script_fonts.ScriptFont, "url", property(lambda _self: url))
            script_fonts.install_script_fonts(tmp_path)
        return destination

    return fetch, destination


@pytest.mark.parametrize("status", [503, 502, 429])
def test_a_temporary_server_error_is_retried_and_the_pin_still_checked(
    flaky_host, download, status
):
    url, answers, requests = flaky_host
    fetch, destination = download
    answers.append(status)

    fetch(url)

    assert destination.read_bytes() == _BODY
    assert len(requests) == 2


def test_a_host_that_stays_busy_fails_after_the_retries(flaky_host, download):
    url, answers, requests = flaky_host
    fetch, destination = download
    answers.extend([503] * 10)

    with pytest.raises((HTTPError, httpx.HTTPStatusError)):
        fetch(url)

    assert len(requests) == 4
    assert not destination.exists()


def test_a_missing_file_fails_at_once(flaky_host, download):
    url, answers, requests = flaky_host
    fetch, destination = download
    answers.append(404)

    with pytest.raises((HTTPError, httpx.HTTPStatusError)):
        fetch(url)

    assert len(requests) == 1
    assert not destination.exists()
