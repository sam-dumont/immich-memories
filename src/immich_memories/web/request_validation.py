"""Reject JSON text that cannot travel through the API and CLI unchanged."""

from __future__ import annotations

import json
import re
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.requests import ClientDisconnect


async def validate_json_request(request: Request, call_next: Any) -> Response:
    """Validate strings before field errors can echo them or commands consume them."""
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if not media_type or media_type == "application/json" or media_type.endswith("+json"):
        try:
            body = await request.body()
        except ClientDisconnect:
            return Response(status_code=400)
        if not body:
            return await call_next(request)
        if error := _json_error(body):
            return error
    return await call_next(request)


def _json_error(body: bytes) -> JSONResponse | None:
    try:
        pending = [(json.loads(body), 0)]
    except (ValueError, UnicodeError, RecursionError):
        return JSONResponse({"detail": "Invalid or excessively nested JSON"}, status_code=400)
    while pending:
        value, depth = pending.pop()
        if depth > 64:
            return JSONResponse({"detail": "JSON nesting exceeds 64 levels"}, status_code=400)
        if isinstance(value, str) and re.search(r"[\x00\ud800-\udfff]", value):
            return JSONResponse(
                {"detail": "JSON strings must contain valid Unicode without NUL"},
                status_code=422,
            )
        if isinstance(value, dict):
            pending.extend((key, depth + 1) for key in value)
            pending.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            pending.extend((item, depth + 1) for item in value)
    return None
