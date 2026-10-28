"""Runs reach an OpenTelemetry collector as live traces, over the real OTLP/HTTP wire."""

from __future__ import annotations

import json
import logging
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

from immich_memories.tracking import otel, timing


class _Receiver(BaseHTTPRequestHandler):
    received: list[tuple[str, dict[str, str], bytes]] = []

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.received.append((self.path, dict(self.headers), body))
        self.send_response(200)
        self.send_header("Content-Type", "application/x-protobuf")
        self.end_headers()

    def log_message(self, *args) -> None:
        pass


def _attributes(pairs) -> dict:
    return {pair.key: getattr(pair.value, pair.value.WhichOneof("value")) for pair in pairs}


def _decode(body: bytes) -> list[dict]:
    request = ExportTraceServiceRequest.FromString(body)
    return [
        {
            "name": span.name,
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


class _Collected:
    def spans(self) -> list[dict]:
        otel.flush()
        return [span for _, _, body in _Receiver.received for span in _decode(body)]

    def named(self) -> dict[str, dict]:
        return {span["name"]: span for span in self.spans()}


@pytest.fixture(autouse=True)
def _tracing_off_after():
    yield
    otel.shutdown()


@pytest.fixture
def collector(monkeypatch):
    """A real HTTP receiver on localhost, the app pointed at it through the standard variables."""
    _Receiver.received = []
    server = HTTPServer(("127.0.0.1", 0), _Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.delenv("TRACEPARENT", raising=False)
    yield _Collected()
    otel.shutdown()
    server.shutdown()
    server.server_close()


def _observed(work):
    from immich_memories.db import open_store
    from immich_memories.tracking.run_observations import observe_run

    with observe_run(open_store(), source="manual", capture_system=False) as tracker:
        work()
    return tracker


def test_a_finished_stage_reaches_the_collector_while_the_run_is_still_going(collector):
    otel.setup()
    seen_during_run: list[str] = []

    def work():
        with timing.span("preparation.scan", items=12):
            pass
        seen_during_run.extend(span["name"] for span in collector.spans())

    _observed(work)

    assert seen_during_run == ["preparation.scan"]
    assert "run" in collector.named()


def test_a_run_arrives_as_one_trace_with_its_stages_nested(collector, monkeypatch):
    from immich_memories.analysis.llm import metrics as llm_metrics
    from immich_memories.db import open_store
    from immich_memories.tracking.span_store import SpanStore

    monkeypatch.setenv("OTEL_SERVICE_NAME", "memories-lab")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "authorization=Bearer%20lab-token")
    otel.setup()

    def work():
        with timing.span("preparation.scan", items=12):
            llm_metrics.record_reply(prompt_tokens=300, completion_tokens=40, stage="captions")
            timing.active().interval("stage.analysis.captions", timing.clock(), 0.0, 7)
        with pytest.raises(ValueError), timing.span("render.music"):
            raise ValueError("no track")

    tracker = _observed(work)

    spans = collector.named()
    assert {path for path, _, _ in _Receiver.received} == {"/v1/traces"}
    assert {headers["authorization"] for _, headers, _ in _Receiver.received} == {
        "Bearer lab-token"
    }
    run = spans["run"]
    assert run["resource"]["service.name"] == "memories-lab"
    assert {span["trace_id"] for span in spans.values()} == {run["trace_id"]}
    assert run["parent"] is None
    assert spans["preparation.scan"]["parent"] == run["span_id"]
    assert spans["preparation.scan"]["attributes"]["items"] == 12
    interval = spans["stage.analysis.captions"]
    assert interval["parent"] == spans["preparation.scan"]["span_id"]
    assert interval["attributes"]["items"] == 7
    assert spans["preparation.scan"]["start"] <= interval["start"] <= interval["end"]
    assert interval["end"] <= spans["preparation.scan"]["end"]
    music = spans["render.music"]
    assert music["status"] == 2
    assert music["events"][0][0] == "exception"
    assert music["events"][0][1]["exception.type"] == "ValueError"
    assert run["attributes"]["run.id"] == tracker.run_id
    assert run["attributes"]["run.status"] == "completed"
    assert run["attributes"]["run.source"] == "manual"
    assert run["attributes"]["llm.prompt_tokens"] == 300
    assert run["attributes"]["llm.stage.captions.completion_tokens"] == 40
    assert run["start"] <= spans["preparation.scan"]["start"]
    assert music["end"] <= run["end"]
    assert SpanStore(open_store()).diagnostics(tracker.run_id)["trace_id"] == run["trace_id"]


def test_a_failed_run_marks_its_root_span_failed(collector):
    otel.setup()

    def work():
        raise RuntimeError("Immich went away")

    with pytest.raises(RuntimeError):
        _observed(work)

    run = collector.named()["run"]
    assert run["status"] == 2
    assert run["attributes"]["run.status"] == "failed"
    assert run["events"][0][1]["exception.type"] == "RuntimeError"


def test_a_warning_inside_a_stage_is_an_event_on_its_span(collector):
    otel.setup()

    def work():
        with timing.span("selection.edit"):
            logging.getLogger("immich_memories.selection").warning("Only 3 clips left")

    _observed(work)

    events = collector.named()["selection.edit"]["events"]
    assert [name for name, _ in events] == ["warning"]
    assert events[0][1]["message"].endswith("Only 3 clips left")


def test_without_an_endpoint_tracing_stays_off(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
    otel.setup()
    seen: list[str | None] = []

    tracker = _observed(lambda: seen.append(otel.current_trace_id()))

    assert seen == [None]
    assert tracker.db.get_run(tracker.run_id).status == "completed"


def test_an_unreachable_collector_costs_one_warning_and_no_secret(monkeypatch, caplog):
    # Port 9 (discard) on loopback: nothing listens, the connection is refused at once.
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:9/otlp-secret-path")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "authorization=Bearer%20lab-token")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TIMEOUT", "300")
    otel.setup()
    with caplog.at_level(logging.WARNING):
        tracker = _observed(lambda: None)
        otel.flush()
        _observed(lambda: None)
        otel.flush()
    assert tracker.db.get_run(tracker.run_id).status == "completed"
    lines = [record.getMessage() for record in caplog.records if record.levelno >= logging.WARNING]
    assert len([line for line in lines if "OTLP" in line]) == 1
    assert not [line for line in lines if "otlp-secret-path" in line or "lab-token" in line]


def test_grpc_is_refused_with_a_warning_instead_of_a_silent_drop(collector, monkeypatch, caplog):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc")
    with caplog.at_level(logging.WARNING, logger="immich_memories"):
        otel.setup()
        _observed(lambda: None)
    assert collector.spans() == []
    assert any("http/protobuf" in record.getMessage() for record in caplog.records)


def test_a_run_started_by_another_process_joins_that_process_trace(collector, monkeypatch):
    parent_trace, parent_span = "4bf92f3577b34da6a3ce929d0e0e4736", "00f067aa0ba902b7"
    monkeypatch.setenv("TRACEPARENT", f"00-{parent_trace}-{parent_span}-01")
    otel.setup()

    _observed(lambda: None)

    run = collector.named()["run"]
    assert run["trace_id"] == parent_trace
    assert run["parent"] == parent_span


def test_a_generation_child_inherits_the_current_span(collector):
    from immich_memories.automation.runner import _execute_generate

    otel.setup()
    with timing.span("automation.generate"):
        trace_id = otel.current_trace_id()
        result = _execute_generate(
            [sys.executable, "-c", "import os; print(os.environ.get('TRACEPARENT', ''))"]
        )
    span = collector.named()["automation.generate"]
    assert result.stdout.strip().startswith(f"00-{trace_id}-{span['span_id']}-")


def test_a_child_outside_any_span_gets_no_stale_trace(monkeypatch):
    monkeypatch.setenv("TRACEPARENT", "00-11111111111111111111111111111111-2222222222222222-01")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert "TRACEPARENT" not in otel.child_environment()


def test_a_web_job_is_a_span_its_child_runs_under(collector, tmp_path):
    from immich_memories.web.jobs import JobRunner

    otel.setup()
    runner = JobRunner(tmp_path)
    job = runner.start(
        "render",
        [sys.executable, "-c", "import os; print(os.environ.get('TRACEPARENT', ''))"],
    )
    while runner.get(job.id).status == "running":
        threading.Event().wait(0.05)

    span = collector.named()["job.render"]
    printed = runner.log_path(job.id).read_text().strip()
    assert printed.startswith(f"00-{span['trace_id']}-{span['span_id']}-")
    assert span["attributes"]["job.id"] == job.id
    assert span["attributes"]["process.exit.code"] == 0


def _json_line() -> dict:
    from immich_memories.logging_config import JsonFormatter, RunIdFilter

    record = logging.LogRecord("immich_memories.x", logging.INFO, "", 0, "hello", (), None)
    RunIdFilter().filter(record)
    return json.loads(JsonFormatter().format(record))


def test_a_json_log_line_names_the_span_it_was_written_in(collector):
    otel.setup()
    assert "trace_id" not in _json_line()
    with timing.span("selection"):
        line = _json_line()
        trace_id = otel.current_trace_id()
    span = collector.named()["selection"]
    assert line["trace_id"] == trace_id == span["trace_id"]
    assert line["span_id"] == span["span_id"]


def test_relayed_phase_lines_carry_the_trace_of_the_work_that_relays_them(collector):
    from immich_memories.automation.phase_log import log_phase_progress
    from immich_memories.logging_config import JsonFormatter, RunIdFilter

    otel.setup()
    lines: list[dict] = []

    class Keep(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            RunIdFilter().filter(record)
            lines.append(json.loads(JsonFormatter().format(record)))

    events = [(1, {"phase": "selection", "label": "Selection", "message": "Editing"})]
    relay = logging.getLogger("immich_memories.automation.phase_log")
    handler = Keep()
    relay.addHandler(handler)
    previous = relay.level
    relay.setLevel(logging.INFO)
    try:
        with timing.span("automation.generate"):
            trace_id = otel.current_trace_id()
            with log_phase_progress(lambda after: [e for e in events if e[0] > after], 0.01):
                threading.Event().wait(0.1)
    finally:
        relay.removeHandler(handler)
        relay.setLevel(previous)
    assert lines
    assert {line.get("trace_id") for line in lines} == {trace_id}


def test_a_reader_retry_stage_is_named_without_its_server():
    from immich_memories.analysis.llm.provider_status import watch_provider
    from immich_memories.analysis.llm.wire import LLMTransportAttempt
    from immich_memories.config.models.llm import LLMConfig
    from immich_memories.operations.cut_progress import announcing_stages

    heard = []
    observe = watch_provider("reader", LLMConfig(base_url="http://10.9.8.7:8000/v1"))
    with announcing_stages(heard.append):
        observe(LLMTransportAttempt(attempt=1, outcome="connection_error", status_code=None))
        observe(LLMTransportAttempt(attempt=99, outcome="connection_error", status_code=None))
    assert [update.stage_key for update in heard] == [
        "Waiting for the reader",
        "Gave up on the reader",
    ]
    assert "10.9.8.7" in heard[0].label
