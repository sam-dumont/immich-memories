"""The web client's own spans, so a trace starts at the click that started the work.

The browser never talks to the collector: it may sit on a private network, need a token, or
refuse cross-origin posts. The client sends its OTLP/JSON batch here and the server forwards
it with its own settings, after taking out what would identify the library: query strings,
asset ids and paths. With tracing off the client is told so and loads nothing.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

from immich_memories.tracking import otel, otel_hops
from immich_memories.web.schemas import TelemetryStatus

router = APIRouter(prefix="/api/v1/telemetry", tags=["telemetry"])

# A browser batch is a few hundred spans at most; anything past this is not one.
MAX_BATCH_BYTES = 1024 * 1024


@router.get("")
def status() -> TelemetryStatus:
    """Whether the server exports traces, and so whether the client should load its tracer."""
    return TelemetryStatus(traces=otel.tracing())


@router.post("/traces", status_code=202)
async def traces(request: Request) -> Response:
    """Forward the client's OTLP/JSON batch to the collector, scrubbed."""
    if not otel.tracing():
        raise HTTPException(404, "Tracing is off")
    media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type != "application/json" and not media_type.endswith("+json"):
        raise HTTPException(415, "Send the batch as application/json")
    body = await request.body()
    if len(body) > MAX_BATCH_BYTES:
        raise HTTPException(413, "Too many spans in one batch")
    try:
        batch = json.loads(body)
    except (ValueError, RecursionError) as error:
        raise HTTPException(400, "Not an OTLP/JSON batch") from error
    if not isinstance(batch, dict) or not isinstance(batch.get("resourceSpans"), list):
        raise HTTPException(400, "Not an OTLP/JSON batch")
    try:
        scrubbed = _scrubbed(batch, quoted=not otel.capturing_content())
    except RecursionError as error:
        raise HTTPException(400, "Not an OTLP/JSON batch") from error
    if not otel.forward(scrubbed):
        raise HTTPException(502, "The collector did not take the spans")
    return Response(status_code=202)


# The text in an OTLP/JSON batch: attribute values and names. Everything else is structure
# (ids, timestamps written as digit strings) that the collector parses and must get untouched.
_TEXT = ("stringValue", "name")


def _scrubbed(value: Any, *, quoted: bool) -> Any:
    """The batch with its text scrubbed and its structure as it came.

    With content capture off, an error's own words (an exception's message, a status message)
    are replaced: a page's error can quote what the server answered, a person's name included.
    """
    if isinstance(value, dict):
        if quoted and value.get("key") == "exception.message":
            return {**value, "value": {"stringValue": otel.HIDDEN}}
        return {key: _scrubbed_field(key, item, quoted) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrubbed(item, quoted=quoted) for item in value]
    return value


def _scrubbed_field(key: str, item: Any, quoted: bool) -> Any:
    if key == "status" and isinstance(item, dict) and isinstance(item.get("message"), str):
        message = otel.HIDDEN if quoted and item["message"] else otel_hops.scrub(item["message"])
        return {**item, "message": message}
    if key in _TEXT and isinstance(item, str):
        return otel_hops.scrub(item)
    return _scrubbed(item, quoted=quoted)
