"""Traces for an OpenTelemetry collector: the SDK when an OTLP endpoint is set, a no-op otherwise.

`timing.span` opens one of these beside each measured span, so a run's spans leave as they
close: an hour-long render is visible while it runs, and a killed pod keeps what it already
sent. The standard `OTEL_*` variables configure everything; nothing loads the SDK unless
`OTEL_EXPORTER_OTLP_ENDPOINT` (or `..._TRACES_ENDPOINT`) is set.

One trace spans processes. A parent passes its current span to the child it starts through
`TRACEPARENT`/`TRACESTATE` (the spec's environment-variable carrier), and `setup()` in the child
picks it up, so a film started from the web page or the scheduler sits under the work that
started it.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any

from opentelemetry import context, propagate, trace
from opentelemetry.trace import Span, Status, StatusCode

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SpanExporter

logger = logging.getLogger(__name__)

SERVICE_NAME = "immich-memories"
# OTLP's default export timeout, in milliseconds as the spec states it.
_TIMEOUT_MS = 10_000
# Warnings become span events; a stage that logged thousands keeps its count, not every line.
EVENTS_PER_SPAN = 20
# The spec's names for W3C trace context carried in a child's environment.
_CARRIER = {"traceparent": "TRACEPARENT", "tracestate": "TRACESTATE"}

# Every span's times come from one monotonic clock anchored to the wall once, so spans measured
# live and intervals folded in from `perf_counter` readings nest exactly, to the nanosecond.
_ANCHOR = time.time() - time.perf_counter()

_provider: TracerProvider | None = None
_inherited: object | None = None
_warned = False


def traces_endpoint() -> str | None:
    """Where traces go, by the OTLP exporter rules: the signal URL as-is, else base + path."""
    if os.environ.get("OTEL_SDK_DISABLED", "").strip().lower() == "true":
        return None
    if signal := os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "").strip():
        return signal
    if base := os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip():
        return base.rstrip("/") + "/v1/traces"
    return None


def setup() -> None:
    """Start exporting when an endpoint is configured, under the trace that started this process."""
    global _provider, _inherited
    if _provider is not None or traces_endpoint() is None:
        return
    protocol = _setting("PROTOCOL", "http/protobuf").lower()
    if protocol != "http/protobuf":
        logger.warning(
            "Trace export is off: this app sends OTLP over HTTP only. Set "
            "OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf and point the endpoint at the "
            "collector's HTTP port (4318)."
        )
        return
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create({"service.version": _version(), "process.pid": os.getpid()})
    if str(resource.attributes.get("service.name", "")).startswith("unknown_service"):
        resource = resource.merge(Resource({"service.name": SERVICE_NAME}))
    _provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(timeout=_timeout_seconds())
    _provider.add_span_processor(BatchSpanProcessor(_quiet(exporter)))
    # The exporter logs each failed batch with the collector's reply; one line of ours is enough.
    logging.getLogger("opentelemetry.exporter").setLevel(logging.CRITICAL)
    inherited = propagate.extract(
        {key: value for key, name in _CARRIER.items() if (value := os.environ.get(name))}
    )
    _inherited = context.attach(inherited)


def flush() -> None:
    """Send what is buffered now; the processor would otherwise wait for its next batch."""
    if _provider is not None:
        _provider.force_flush()


def shutdown() -> None:
    """Send what is left and stop exporting, so `setup()` can start again."""
    global _provider, _inherited, _warned
    if _provider is None:
        return
    _provider.shutdown()
    _provider = None
    if _inherited is not None:
        context.detach(_inherited)  # type: ignore[arg-type]
        _inherited = None
    _warned = False


def tracer() -> trace.Tracer:
    """The app's tracer: the SDK's while exporting, the API's no-op otherwise."""
    if _provider is None:
        return trace.NoOpTracer()
    return _provider.get_tracer("immich_memories", _version())


def current_trace_id() -> str | None:
    """The trace the current span belongs to, as hex, or None when nothing is traced."""
    return log_fields().get("trace_id")


def log_fields() -> dict[str, str]:
    """The `trace_id`/`span_id` pair a log line carries to link it to its span."""
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return {}
    return {
        "trace_id": format(span_context.trace_id, "032x"),
        "span_id": format(span_context.span_id, "016x"),
    }


def child_environment(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """`env` (default: this process's) carrying the current span to a child process.

    A trace this process inherited but is no longer inside is dropped, so a child never
    claims a parent that already ended.
    """
    child = dict(os.environ if env is None else env)
    for name in _CARRIER.values():
        child.pop(name, None)
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    for key, name in _CARRIER.items():
        if key in carrier:
            child[name] = carrier[key]
    return child


@contextmanager
def current(span: Span) -> Iterator[Span]:
    """Make `span` the parent of what runs inside, without ending it on the way out."""
    token = context.attach(trace.set_span_in_context(span))
    try:
        yield span
    finally:
        context.detach(token)


def start(
    name: str, attributes: Mapping[str, Any] | None = None, *, at: float | None = None
) -> Span:
    """Open a span under the current one; `at` is a wall-clock start in seconds (default: now)."""
    return tracer().start_span(
        name,
        attributes=_clean(attributes or {}),
        start_time=_nanos(wall(time.perf_counter()) if at is None else at),
    )


def end(span: Span, at: float | None = None) -> None:
    """Close `span` on the same clock it opened on; `at` is wall-clock seconds (default: now)."""
    span.end(end_time=_nanos(wall(time.perf_counter()) if at is None else at))


def interval(name: str, started: float, ended: float, attributes: Mapping[str, Any]) -> None:
    """A span for time already measured, between two wall-clock instants in seconds."""
    end(start(name, attributes, at=started), at=ended)


def wall(perf: float) -> float:
    """A `perf_counter` reading as wall-clock seconds, for spans measured on the run's clock."""
    return _ANCHOR + perf


def _nanos(seconds: float) -> int:
    return int(seconds * 1e9)


def record_error(span: Span, error: Mapping[str, Any]) -> None:
    """Mark `span` failed with the error `timing` kept: redacted, app frames only."""
    span.add_event(
        "exception",
        {
            "exception.type": error["type"],
            "exception.message": error["message"],
            "exception.stacktrace": "\n".join(error["frames"]),
        },
    )
    span.set_status(Status(StatusCode.ERROR, error["type"]))


def mark_failed(span: Span, error_type: str, reason: str) -> None:
    """Fail `span` with a reason the app wrote, for errors whose own text may hold settings."""
    record_error(span, {"type": error_type, "message": reason, "frames": []})


def finish_run(
    span: Span, *, run_id: str, status: str, source: str, llm: Mapping[str, Any]
) -> None:
    """The run's outcome and LLM spend, set on its root span once both are saved."""
    outcome = {"run.id": run_id, "run.status": status, "run.source": source}
    span.set_attributes(outcome | _llm_attributes(llm))
    if status == "failed":
        span.set_status(Status(StatusCode.ERROR, "run failed"))


def _llm_attributes(llm: Mapping[str, Any]) -> dict[str, Any]:
    # Totals and per-stage spend; per-model spend arrives with the GenAI spans (#2887).
    flat = {f"llm.{key}": value for key, value in llm.items() if isinstance(value, int | float)}
    for stage, spend in llm.get("by_stage", {}).items():
        for key, value in spend.items():
            if value:
                flat[f"llm.stage.{stage}.{key}"] = value
    return flat


def _clean(attributes: Mapping[str, Any]) -> dict[str, Any]:
    # OTel takes str, bool, int, float and lists of one of them; None means "not known".
    return {key: value for key, value in attributes.items() if value is not None}


def _setting(name: str, default: str = "") -> str:
    """A trace-specific OTLP variable wins over the general one, as the SDKs read them."""
    for key in (f"OTEL_EXPORTER_OTLP_TRACES_{name}", f"OTEL_EXPORTER_OTLP_{name}"):
        if value := os.environ.get(key, "").strip():
            return value
    return default


def _timeout_seconds() -> float:
    # The spec gives OTEL_EXPORTER_OTLP_TIMEOUT in milliseconds; the Python exporter reads
    # seconds, which would turn the documented 10000 into almost three hours of retries.
    try:
        return int(_setting("TIMEOUT", str(_TIMEOUT_MS))) / 1000
    except ValueError:
        return _TIMEOUT_MS / 1000


def _version() -> str:
    try:
        return version("immich-memories")
    except PackageNotFoundError:
        return "unknown"


def _quiet(exporter: SpanExporter) -> SpanExporter:
    """Wrap the OTLP exporter: a collector that is down costs one warning, not one per batch."""
    from opentelemetry.sdk.trace import ReadableSpan
    from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

    class Quiet(SpanExporter):
        def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
            global _warned
            try:
                result = exporter.export(spans)
            except Exception:  # noqa: BLE001 - telemetry must never fail the work it describes
                result = SpanExportResult.FAILURE
            if result is SpanExportResult.FAILURE and not _warned:
                _warned = True
                # The endpoint and headers are settings: say what failed, not where.
                logger.warning("OTLP trace export failed: the collector did not accept the spans")
            return result

        def shutdown(self) -> None:
            exporter.shutdown()

        def force_flush(self, timeout_millis: int = 30_000) -> bool:
            return exporter.force_flush(timeout_millis)

    return Quiet()
