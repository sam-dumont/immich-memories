"""Pinned downloads follow HTTP redirects and refuse other protocols before reading bytes."""

from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.error import HTTPError

import pytest

from immich_memories.pinned_models import fetch_pinned_model
from immich_memories.titles import script_fonts

_BODY = b"synthetic pinned artifact"


@pytest.fixture
def redirect_server():
    redirects = {}
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 -- stdlib server interface
            requests.append(self.path)
            if self.path in redirects:
                self.send_response(302)
                self.send_header("Location", redirects[self.path])
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(_BODY)))
            self.end_headers()
            self.wfile.write(_BODY)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", redirects, requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture(params=["model", "font"])
def download(request, monkeypatch, tmp_path):
    destination = tmp_path / "artifact"
    digest = hashlib.sha256(_BODY).hexdigest()

    def fetch(url):
        if request.param == "model":
            fetch_pinned_model(url=url, destination=destination, sha256=digest)
        else:
            font = script_fonts.ScriptFont("artifact", digest, len(_BODY))
            # WHY: use one synthetic pin and a loopback source; fetching and verification stay real.
            monkeypatch.setattr(script_fonts, "SCRIPT_FONTS", (font,))
            monkeypatch.setattr(script_fonts.ScriptFont, "url", property(lambda _self: url))
            script_fonts.install_script_fonts(tmp_path)
        return destination

    return fetch, destination


def test_http_redirects_still_verify_the_pinned_artifact(redirect_server, download):
    base, redirects, requests = redirect_server
    redirects["/start"] = "/hop"
    redirects["/hop"] = f"{base}/artifact"
    fetch, destination = download

    fetch(f"{base}/start")

    assert destination.read_bytes() == _BODY
    assert requests == ["/start", "/hop", "/artifact"]


@pytest.mark.parametrize("scheme", ["ftp", "file"])
def test_a_redirect_to_another_protocol_installs_nothing(redirect_server, download, scheme):
    base, redirects, requests = redirect_server
    redirects["/start"] = "/hop"
    redirects["/hop"] = f"{scheme}://127.0.0.1/never-read"
    fetch, destination = download

    with pytest.raises((ValueError, HTTPError)):
        fetch(f"{base}/start")

    assert requests == ["/start", "/hop"]
    assert not destination.exists()
    assert not destination.with_name("artifact.partial").exists()
