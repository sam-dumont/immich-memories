"""A real OTLP/HTTP receiver on localhost that decodes what the SDK sends, for trace tests."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

from immich_memories.tracking import otel


class Received:
    """What the receiver got: raw requests, and their spans decoded to plain dicts."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, str], bytes]] = []

    def spans(self) -> list[dict]:
        otel.flush()
        # Forwarded browser batches arrive as OTLP JSON; the SDK's own exports are protobuf.
        return [
            span
            for _, headers, body in self.requests
            if "json" not in headers.get("Content-Type", "")
            for span in decode(body)
        ]

    def own(self) -> list[dict]:
        """The app's own spans: not the HTTP, store and program hops around them."""
        return [
            span
            for span in self.spans()
            if span["kind"] in (0, 1) and not span["name"].startswith("exec ")
        ]

    def named(self) -> dict[str, dict]:
        return {span["name"]: span for span in self.spans()}


def _value(value):
    kind = value.WhichOneof("value")
    if kind == "array_value":
        return [_value(item) for item in value.array_value.values]
    return getattr(value, kind)


def _attributes(pairs) -> dict:
    return {pair.key: _value(pair.value) for pair in pairs}


def decode(body: bytes) -> list[dict]:
    request = ExportTraceServiceRequest.FromString(body)
    return [
        {
            "name": span.name,
            "kind": span.kind,
            "trace_id": span.trace_id.hex(),
            "span_id": span.span_id.hex(),
            "parent": span.parent_span_id.hex() or None,
            "attributes": _attributes(span.attributes),
            "status": span.status.code,
            "events": [(event.name, _attributes(event.attributes)) for event in span.events],
            "start": span.start_time_unix_nano,
            "end": span.end_time_unix_nano,
            "resource": _attributes(spans.resource.attributes),
        }
        for spans in request.resource_spans
        for scope in spans.scope_spans
        for span in scope.spans
    ]


@contextmanager
def receiving(monkeypatch) -> Iterator[Received]:
    """Point the standard OTLP variables at a fresh receiver; stop exporting afterwards."""
    received = Received()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.requests.append((self.path, dict(self.headers), body))
            self.send_response(200)
            self.send_header("Content-Type", "application/x-protobuf")
            self.end_headers()

        def log_message(self, *args) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.delenv("TRACEPARENT", raising=False)
    try:
        yield received
    finally:
        otel.shutdown()
        server.shutdown()
        server.server_close()
