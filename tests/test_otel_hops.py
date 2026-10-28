"""The hops a run makes are spans too: web routes, HTTP calls, store queries, child programs."""

from __future__ import annotations

import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import sqlalchemy as sa

from immich_memories.tracking import otel, timing
from tests.otel_receiver import receiving

_SERVER = 2
_CLIENT = 3
_ASSET = "8c1e2b4a-0f6d-4c55-9a3e-5d2f7b9e1a00"


@pytest.fixture
def collector(monkeypatch):
    with receiving(monkeypatch) as received:
        otel.setup()
        yield received


class _Upstream(BaseHTTPRequestHandler):
    headers_seen: list[dict[str, str]] = []

    def do_GET(self) -> None:
        self.headers_seen.append(dict(self.headers))
        body = b"x" * 321
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def upstream():
    _Upstream.headers_seen = []
    server = HTTPServer(("127.0.0.1", 0), _Upstream)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_port
    server.shutdown()
    server.server_close()


def test_an_http_call_is_a_client_span_with_no_asset_id_and_no_query(collector, upstream):
    import httpx

    with timing.span("discovery"):
        url = f"http://127.0.0.1:{upstream}/api/assets/{_ASSET}/thumbnail?key=shared-secret"
        assert httpx.get(url).status_code == 200

    spans = collector.spans()
    call = next(span for span in spans if span["kind"] == _CLIENT)
    discovery = next(span for span in spans if span["name"] == "discovery")
    assert call["name"] == "GET /api/assets/{id}/thumbnail"
    assert call["parent"] == discovery["span_id"]
    flat = repr(call)
    assert _ASSET not in flat
    assert "shared-secret" not in flat
    assert call["attributes"]["http.response.status_code"] == 200
    assert call["attributes"]["http.response.body.size"] == 321
    traceparent = _Upstream.headers_seen[0]["traceparent"]
    assert traceparent.startswith(f"00-{call['trace_id']}-{call['span_id']}-")


def test_a_store_query_is_a_span_without_its_bound_values(collector, tmp_path):
    from immich_memories.db.bootstrap import StoreLocation
    from immich_memories.db.engine import create_store_engine

    engine = create_store_engine(StoreLocation(url=f"sqlite:///{tmp_path / 'store.db'}"))
    with timing.span("selection"), engine.connect() as connection:
        connection.execute(sa.text("SELECT :name AS name"), {"name": "private-person-name"})

    query = next(span for span in collector.spans() if span["name"].startswith("SELECT"))
    assert query["kind"] == _CLIENT
    assert query["attributes"].get("db.system.name", query["attributes"].get("db.system")) == (
        "sqlite"
    )
    assert "private-person-name" not in repr(query)


def test_a_child_program_is_a_span_with_its_exit_code_and_no_private_path(collector, tmp_path):
    private = tmp_path / "home" / f"IMG_{_ASSET}.mov"
    with timing.span("render.assembly"):
        subprocess.run([sys.executable, "-c", "import sys; sys.exit(3)", str(private)], check=False)

    span = next(span for span in collector.spans() if span["name"].startswith("exec "))
    assert span["name"] == f"exec {sys.executable.rsplit('/', 1)[-1]}"
    assert span["attributes"]["process.exit.code"] == 3
    assert span["status"] == 2
    arguments = span["attributes"]["process.command_args"]
    assert "IMG_{id}.mov" in arguments
    assert str(tmp_path) not in repr(span)
    assert _ASSET not in repr(span)


def test_a_web_route_is_a_server_span_under_the_caller_trace(collector):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()

    @app.get("/api/v1/films/{film_id}")
    def film(film_id: str) -> dict[str, str]:
        with timing.span("film.read"):
            return {"id": film_id}

    otel.instrument_app(app)
    parent = "4bf92f3577b34da6a3ce929d0e0e4736"
    with TestClient(app) as client:
        client.get(
            f"/api/v1/films/{_ASSET}", headers={"traceparent": f"00-{parent}-00f067aa0ba902b7-01"}
        )
        client.get("/health/live")

    spans = collector.spans()
    route = next(span for span in spans if span["kind"] == _SERVER)
    assert route["name"] == "GET /api/v1/films/{film_id}"
    assert route["trace_id"] == parent
    assert next(span for span in spans if span["name"] == "film.read")["trace_id"] == parent
    assert _ASSET not in repr(route)
    assert not [span for span in spans if "health" in span["name"]]


def test_without_tracing_nothing_is_patched(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    original = subprocess.Popen.__init__
    otel.setup()
    assert subprocess.Popen.__init__ is original
    otel.shutdown()
    assert subprocess.Popen.__init__ is original
