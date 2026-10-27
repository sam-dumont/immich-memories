"""Send a finished run to an OpenTelemetry collector as one trace, over OTLP/HTTP.

The saved spans stay the source of truth: this reads the same buffer `SpanStore` saves and
posts it once, after the run's outcome is known. Nothing here runs unless the standard
`OTEL_EXPORTER_OTLP_ENDPOINT` (or `..._TRACES_ENDPOINT`) is set, and the body is OTLP's JSON
encoding, which every collector's HTTP receiver accepts beside protobuf, so the export needs
no SDK and the default install carries no new dependency.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, version
from typing import Any
from urllib.parse import unquote

from immich_memories.tracking.timing import Collector, Span

logger = logging.getLogger(__name__)

SERVICE_NAME = "immich-memories"
# OTLP's own default for an HTTP export.
_TIMEOUT_MS = 10_000
# Warnings become span events; a run that logged thousands keeps its count, not every line.
_EVENTS_PER_SPAN = 20
_ERROR = 2
_INTERNAL = 1


def traces_endpoint() -> str | None:
    """Where traces go, by the OTLP exporter rules: the signal URL as-is, else base + path."""
    if os.environ.get("OTEL_SDK_DISABLED", "").strip().lower() == "true":
        return None
    if signal := os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "").strip():
        return signal
    if base := os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip():
        return base.rstrip("/") + "/v1/traces"
    return None


def run_trace_id(run_id: str) -> str:
    """A run's trace id, derived so a log line can name it before the trace is sent."""
    return hashlib.sha256(f"immich-memories run {run_id}".encode()).hexdigest()[:32]


def export_run(
    collected: Collector,
    *,
    run_id: str,
    status: str,
    source: str,
    llm: Mapping[str, Any],
) -> None:
    """Post the run's spans; a collector that is down costs one warning, never the run."""
    endpoint = traces_endpoint()
    if endpoint is None:
        return
    protocol = _setting("PROTOCOL", "http/protobuf").lower()
    if protocol not in ("http/protobuf", "http/json"):
        logger.warning(
            "OTLP export skipped: this app sends over HTTP only. Set "
            "OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf and point the endpoint at the "
            "collector's HTTP port (4318)."
        )
        return
    body = _payload(collected, run_id=run_id, status=status, source=source, llm=llm)
    _post(endpoint, body)


def _setting(name: str, default: str = "") -> str:
    """A trace-specific OTLP variable wins over the general one, as the SDKs read them."""
    for key in (f"OTEL_EXPORTER_OTLP_TRACES_{name}", f"OTEL_EXPORTER_OTLP_{name}"):
        if value := os.environ.get(key, "").strip():
            return value
    return default


def _pairs(raw: str) -> dict[str, str]:
    # W3C baggage format, which OTEL_EXPORTER_OTLP_HEADERS and OTEL_RESOURCE_ATTRIBUTES share.
    pairs = {}
    for item in raw.split(","):
        key, sep, value = item.partition("=")
        if sep and key.strip():
            pairs[unquote(key.strip())] = unquote(value.strip())
    return pairs


def _post(endpoint: str, body: dict[str, Any]) -> None:
    import httpx

    headers = _pairs(_setting("HEADERS")) | {"Content-Type": "application/json"}
    try:
        timeout = int(_setting("TIMEOUT", str(_TIMEOUT_MS))) / 1000
    except ValueError:
        timeout = _TIMEOUT_MS / 1000
    try:
        response = httpx.post(endpoint, json=body, headers=headers, timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        # The endpoint and headers are settings: the status says enough without them.
        logger.warning("OTLP export failed: the collector answered %d", error.response.status_code)
    except httpx.HTTPError as error:
        logger.warning("OTLP export failed: %s, the collector did not answer", type(error).__name__)


def _payload(
    collected: Collector, *, run_id: str, status: str, source: str, llm: Mapping[str, Any]
) -> dict[str, Any]:
    trace_id = run_trace_id(run_id)
    # perf_counter has no epoch: anchor it to the wall clock once, now, for every span.
    offset = time.time_ns() - int(collected.now() * 1e9)
    run_attributes = {
        "run.id": run_id,
        "run.status": status,
        "run.source": source,
    } | _llm_attributes(llm)
    spans = [
        _span(
            measured,
            trace_id=trace_id,
            run_id=run_id,
            offset=offset,
            extra=run_attributes if measured.parent_id is None else {},
            failed=measured.parent_id is None and status == "failed",
        )
        for measured in sorted(collected.spans, key=lambda item: item.span_id)
    ]
    resource = {"service.name": SERVICE_NAME, "service.version": _version()}
    resource |= _pairs(os.environ.get("OTEL_RESOURCE_ATTRIBUTES", ""))
    if name := os.environ.get("OTEL_SERVICE_NAME", "").strip():
        resource["service.name"] = name
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": _attributes(resource)},
                "scopeSpans": [
                    {"scope": {"name": "immich_memories", "version": _version()}, "spans": spans}
                ],
            }
        ]
    }


def _span(
    measured: Span,
    *,
    trace_id: str,
    run_id: str,
    offset: int,
    extra: Mapping[str, Any],
    failed: bool,
) -> dict[str, Any]:
    start = offset + int(measured.start * 1e9)
    end = start + int(measured.duration * 1e9)
    attributes: dict[str, Any] = {**measured.attributes, **extra}
    if measured.items is not None:
        attributes["items"] = measured.items
    if measured.peak_rss is not None:
        attributes["process.peak_rss_bytes"] = measured.peak_rss
    if measured.peak_tree_rss is not None:
        attributes["process.peak_tree_rss_bytes"] = measured.peak_tree_rss
    if measured.warnings:
        attributes["warnings"] = len(measured.warnings)
    events = [
        {"timeUnixNano": str(end), "name": "warning", "attributes": _attributes({"message": line})}
        for line in measured.warnings[:_EVENTS_PER_SPAN]
    ]
    span: dict[str, Any] = {
        "traceId": trace_id,
        "spanId": _span_id(run_id, measured.span_id),
        "name": measured.name,
        "kind": _INTERNAL,
        "startTimeUnixNano": str(start),
        "endTimeUnixNano": str(end),
        "attributes": _attributes(attributes),
    }
    if measured.parent_id is not None:
        span["parentSpanId"] = _span_id(run_id, measured.parent_id)
    if measured.error is not None:
        events.append(_exception(measured.error, end))
    if measured.error is not None or failed:
        span["status"] = {"code": _ERROR}
    if events:
        span["events"] = events
    return span


def _exception(error: Mapping[str, Any], at: int) -> dict[str, Any]:
    # Already redacted when the span closed; the frames are paths inside the package only.
    return {
        "timeUnixNano": str(at),
        "name": "exception",
        "attributes": _attributes(
            {
                "exception.type": error["type"],
                "exception.message": error["message"],
                "exception.stacktrace": "\n".join(error["frames"]),
            }
        ),
    }


def _llm_attributes(llm: Mapping[str, Any]) -> dict[str, Any]:
    # Totals and per-stage spend; per-model spend stays in the report, as model names are settings.
    flat = {f"llm.{key}": value for key, value in llm.items() if isinstance(value, int | float)}
    for stage, spend in llm.get("by_stage", {}).items():
        for key, value in spend.items():
            if value:
                flat[f"llm.stage.{stage}.{key}"] = value
    return flat


def _span_id(run_id: str, number: int) -> str:
    return hashlib.sha256(f"{run_id}:{number}".encode()).hexdigest()[:16]


def _attributes(values: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [{"key": key, "value": _value(value)} for key, value in values.items()]


def _value(value: Any) -> dict[str, Any]:
    # OTLP JSON writes 64-bit integers as strings, so no reader loses precision.
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    return {"stringValue": str(value)}


def _version() -> str:
    try:
        return version("immich-memories")
    except PackageNotFoundError:
        return "unknown"
