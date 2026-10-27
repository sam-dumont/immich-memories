"""A run reaches an OpenTelemetry collector as one trace, over the OTLP/HTTP wire."""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from immich_memories.tracking import timing


class _Collector(BaseHTTPRequestHandler):
    received: list[tuple[str, dict[str, str], dict]] = []

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.received.append((self.path, dict(self.headers), json.loads(body)))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def collector(monkeypatch):
    """A real HTTP receiver on localhost, the app pointed at it through the standard variables."""
    _Collector.received = []
    server = HTTPServer(("127.0.0.1", 0), _Collector)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", f"http://127.0.0.1:{server.server_port}")
    yield _Collector.received
    server.shutdown()
    server.server_close()


def _observed(work):
    from immich_memories.db import open_store
    from immich_memories.tracking.run_observations import observe_run

    with observe_run(open_store(), source="manual", capture_system=False) as tracker:
        work()
    return tracker


def _spans(payload: dict) -> list[dict]:
    return [
        span
        for resource in payload["resourceSpans"]
        for scope in resource["scopeSpans"]
        for span in scope["spans"]
    ]


def _attributes(item: dict) -> dict:
    return {
        attribute["key"]: next(iter(attribute["value"].values()))
        for attribute in item["attributes"]
    }


def test_a_run_arrives_as_one_trace_with_its_stages_nested(collector, monkeypatch):
    from immich_memories.analysis.llm import metrics as llm_metrics
    from immich_memories.tracking.otlp_export import run_trace_id

    monkeypatch.setenv("OTEL_SERVICE_NAME", "memories-lab")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "authorization=Bearer%20lab-token")

    def work():
        with timing.span("preparation.scan", items=12):
            llm_metrics.record_reply(prompt_tokens=300, completion_tokens=40, stage="captions")
        with pytest.raises(ValueError), timing.span("render.music"):
            raise ValueError("no track")

    tracker = _observed(work)

    assert len(collector) == 1
    path, headers, payload = collector[0]
    assert path == "/v1/traces"
    assert headers["authorization"] == "Bearer lab-token"
    assert headers["Content-Type"] == "application/json"
    resource = _attributes(payload["resourceSpans"][0]["resource"])
    assert resource["service.name"] == "memories-lab"
    spans = {span["name"]: span for span in _spans(payload)}
    assert {span["traceId"] for span in spans.values()} == {run_trace_id(tracker.run_id)}
    run = spans["run"]
    assert "parentSpanId" not in run
    assert spans["preparation.scan"]["parentSpanId"] == run["spanId"]
    assert _attributes(spans["preparation.scan"])["items"] == "12"
    assert spans["render.music"]["status"]["code"] == 2
    assert _attributes(spans["render.music"]["events"][0])["exception.type"] == "ValueError"
    run_attributes = _attributes(run)
    assert run_attributes["run.id"] == tracker.run_id
    assert run_attributes["run.status"] == "completed"
    assert run_attributes["llm.prompt_tokens"] == "300"
    assert run_attributes["llm.stage.captions.completion_tokens"] == "40"
    assert int(run["startTimeUnixNano"]) <= int(spans["preparation.scan"]["startTimeUnixNano"])
    assert int(spans["render.music"]["endTimeUnixNano"]) <= int(run["endTimeUnixNano"])


def test_a_failed_run_marks_its_root_span_failed(collector):
    def work():
        raise RuntimeError("Immich went away")

    with pytest.raises(RuntimeError):
        _observed(work)

    run = next(span for span in _spans(collector[0][2]) if span["name"] == "run")
    assert run["status"]["code"] == 2
    assert _attributes(run)["run.status"] == "failed"


def test_without_an_endpoint_nothing_is_sent(monkeypatch):
    import httpx

    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)

    def refuse(*args, **kwargs):
        raise AssertionError("no endpoint is configured, so nothing may be sent")

    # WHY: the network boundary; an unconfigured install must never open a connection.
    monkeypatch.setattr(httpx, "post", refuse)
    tracker = _observed(lambda: None)
    assert tracker.db.get_run(tracker.run_id).status == "completed"


def test_an_unreachable_collector_costs_the_run_one_warning_and_no_secret(monkeypatch, caplog):
    # Port 9 (discard) on loopback: nothing listens, the connection is refused at once.
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:9/otlp-secret-path")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "authorization=Bearer%20lab-token")
    with caplog.at_level(logging.WARNING, logger="immich_memories"):
        tracker = _observed(lambda: None)
    assert tracker.db.get_run(tracker.run_id).status == "completed"
    warnings = [record.getMessage() for record in caplog.records if "OTLP" in record.getMessage()]
    assert len(warnings) == 1
    assert "otlp-secret-path" not in warnings[0]
    assert "lab-token" not in warnings[0]


def test_grpc_is_refused_with_a_warning_instead_of_a_silent_drop(collector, monkeypatch, caplog):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc")
    with caplog.at_level(logging.WARNING, logger="immich_memories"):
        _observed(lambda: None)
    assert collector == []
    assert any("http/protobuf" in record.getMessage() for record in caplog.records)


def test_a_json_log_line_carries_the_trace_id_only_while_exporting(monkeypatch):
    from immich_memories.logging_config import JsonFormatter, RunIdFilter, set_current_run_id
    from immich_memories.tracking.otlp_export import run_trace_id

    def line() -> dict:
        record = logging.LogRecord("immich_memories.x", logging.INFO, "", 0, "hello", (), None)
        RunIdFilter().filter(record)
        return json.loads(JsonFormatter().format(record))

    set_current_run_id("20261027_101500_a1b2")
    try:
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        assert "trace_id" not in line()
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
        assert line()["trace_id"] == run_trace_id("20261027_101500_a1b2")
    finally:
        set_current_run_id(None)
