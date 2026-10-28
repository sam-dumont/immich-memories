"""The web client's spans reach the collector through the app server, scrubbed, or not at all."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from immich_memories.tracking import otel
from tests.otel_receiver import receiving

_ASSET = "8c1e2b4a-0f6d-4c55-9a3e-5d2f7b9e1a00"
_TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"


def _client() -> TestClient:
    from immich_memories.web import telemetry

    app = FastAPI()
    app.include_router(telemetry.router)
    otel.instrument_app(app)
    return TestClient(app)


def _browser_spans() -> dict:
    """What the OpenTelemetry web exporter posts: OTLP's JSON encoding."""
    url = f"http://memories.local/api/v1/assets/{_ASSET}/thumbnail?key=shared-secret"
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "immich-memories-web"}}
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "@opentelemetry/instrumentation-fetch"},
                        "spans": [
                            {
                                "traceId": _TRACE,
                                "spanId": "00f067aa0ba902b7",
                                "name": "HTTP GET",
                                "kind": 3,
                                "startTimeUnixNano": "1793170000000000000",
                                "endTimeUnixNano": "1793170000100000000",
                                "attributes": [
                                    {"key": "url.full", "value": {"stringValue": url}},
                                    {
                                        "key": "http.response.status_code",
                                        "value": {"intValue": "200"},
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }


@pytest.fixture
def collector(monkeypatch):
    with receiving(monkeypatch) as received:
        otel.setup()
        yield received


def test_with_tracing_off_the_client_is_told_and_nothing_is_taken(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    otel.shutdown()
    client = _client()
    assert client.get("/api/v1/telemetry").json() == {"traces": False}
    assert client.post("/api/v1/telemetry/traces", json=_browser_spans()).status_code == 404


def test_browser_spans_are_forwarded_scrubbed_with_the_server_headers(collector, monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "authorization=Bearer%20lab-token")
    client = _client()

    assert client.get("/api/v1/telemetry").json() == {"traces": True}
    answer = client.post("/api/v1/telemetry/traces", json=_browser_spans())

    assert answer.status_code == 202
    forwarded = [request for request in collector.requests if "json" in request[1]["Content-Type"]]
    assert len(forwarded) == 1
    path, headers, body = forwarded[0]
    assert path == "/v1/traces"
    assert headers["authorization"] == "Bearer lab-token"
    payload = json.loads(body)
    span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert span["traceId"] == _TRACE
    # Timestamps are digit strings the collector parses; they must arrive as they left.
    assert span["startTimeUnixNano"] == "1793170000000000000"
    assert span["endTimeUnixNano"] == "1793170000100000000"
    url = span["attributes"][0]["value"]["stringValue"]
    assert url == "http://memories.local/api/v1/assets/{id}/thumbnail"
    assert _ASSET not in body.decode()
    assert "shared-secret" not in body.decode()


def test_forwarding_makes_no_spans_of_its_own(collector):
    client = _client()
    client.post("/api/v1/telemetry/traces", json=_browser_spans())
    client.get("/api/v1/telemetry")

    assert collector.spans() == []


@pytest.mark.parametrize(
    ("body", "status"),
    [
        (b"x" * (2 * 1024 * 1024), 413),
        (json.dumps({"something": "else"}).encode(), 400),
        (json.dumps({"resourceSpans": "nope"}).encode(), 400),
    ],
    # Named, because pytest would spell the 2 MiB body out in the test id: one 2 MB line in
    # the verbose CI log, which stalls the runner reading it.
    ids=["too-large", "not-otlp", "spans-not-a-list"],
)
def test_what_is_not_a_modest_otlp_batch_is_refused(collector, body, status):
    answer = _client().post(
        "/api/v1/telemetry/traces", content=body, headers={"content-type": "application/json"}
    )
    assert answer.status_code == status
    assert [request for request in collector.requests if "json" in request[1]["Content-Type"]] == []
