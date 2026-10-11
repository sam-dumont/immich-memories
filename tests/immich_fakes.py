"""Fakes of Immich that refuse what the real Immich refuses.

Two layers, one rule: a fake must never accept a call the real thing rejects.

* `fake_immich_client()` builds a client fake with `create_autospec`, so a call with a
  keyword or an argument count the real client does not take raises in the test, as it
  would in production.
* `ImmichWire` wraps an `httpx.MockTransport` handler and checks every request against
  `tests/fixtures/immich-openapi/contract.json`: the Immich OpenAPI specs of the supported
  releases, trimmed by `scripts/trim_immich_openapi.py` to the endpoints the app calls.
  Integers are integers, ids are UUIDs (v4 on v3), enums hold their values, dates match
  the pattern, required fields are present, null only where the spec allows it. A request Immich would answer with 400 gets that 400 here, and the problem is
  recorded so the test can fail on it (`assert_clean`) even when the client swallows it.

Immich drops a parameter its spec does not define without an error. Sending one is
always a bug (the request means less than the code thinks), so the fakes refuse it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import create_autospec

import httpx

from immich_memories.api.immich import ImmichClient, SyncImmichClient

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def fake_immich_client(spec: type = SyncImmichClient) -> Any:
    """A client fake that only accepts the real client's methods and signatures."""
    return create_autospec(spec, instance=True)


def fake_async_immich_client() -> Any:
    return create_autospec(ImmichClient, instance=True)


# ── the request contract, trimmed from the Immich OpenAPI specs ─────────────

CONTRACT_FILE = Path(__file__).resolve().parent / "fixtures" / "immich-openapi" / "contract.json"
# What `scripts/trim_immich_openapi.py` kept: per Immich release, per "METHOD /path", the
# path, query and JSON body parameters with type, format, pattern, enum, bounds, and
# whether each is required or nullable.
CONTRACT: dict[str, dict[str, Any]] = json.loads(CONTRACT_FILE.read_text(encoding="utf-8"))
RELEASES: tuple[str, ...] = tuple(sorted(CONTRACT))
V2: tuple[str, ...] = tuple(r for r in RELEASES if r.startswith("v2."))
V3: tuple[str, ...] = tuple(r for r in RELEASES if r.startswith("v3."))


def _template(path: str) -> re.Pattern[str]:
    return re.compile("^" + re.sub(r"\\\{(\w+)\\\}", r"(?P<\1>[^/]+)", re.escape(path)) + "$")


_ROUTES: dict[str, list[tuple[str, re.Pattern[str], str]]] = {
    release: [
        (key.split(" ", 1)[0], _template(key.split(" ", 1)[1]), key) for key in sorted(endpoints)
    ]
    for release, endpoints in CONTRACT.items()
}


def _is_datetime(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _string_problem(name: str, value: str, spec: dict[str, Any], uuid_ids: bool) -> str | None:
    is_id = spec.get("format") == "uuid"
    if is_id and not uuid_ids:
        return None
    if is_id and not UUID.match(value):
        return f"{name} must be a UUID, got {value!r}"
    if spec.get("format") == "date-time" and not _is_datetime(value):
        return f"{name} must be a date-time, got {value!r}"
    if "pattern" in spec and not re.search(spec["pattern"], value):
        return f"{name} does not match the pattern Immich requires, got {value!r}"
    if "enum" in spec and value not in spec["enum"]:
        return f"{name} must be one of {spec['enum']}, got {value!r}"
    return None


def _bounds_problem(name: str, value: float, spec: dict[str, Any]) -> str | None:
    if "minimum" in spec and value < spec["minimum"]:
        return f"{name} must be at least {spec['minimum']}, got {value}"
    if "maximum" in spec and value > spec["maximum"]:
        return f"{name} must be at most {spec['maximum']}, got {value}"
    return None


def _json_problem(name: str, value: Any, spec: dict[str, Any], uuid_ids: bool) -> str | None:
    """A JSON body value against its contract field: no conversion, as JSON Schema reads it."""
    if value is None:
        return None if spec.get("nullable") else f"{name} must not be null"
    kind = spec.get("type")
    if kind == "string":
        if not isinstance(value, str):
            return f"{name} must be a string, got {value!r}"
        return _string_problem(name, value, spec, uuid_ids)
    if kind in ("integer", "number"):
        # bool is an int in Python and never a number in JSON.
        allowed = (int,) if kind == "integer" else (int, float)
        if isinstance(value, bool) or not isinstance(value, allowed):
            return f"{name} must be {kind}, got {value!r}"
        return _bounds_problem(name, value, spec)
    if kind == "boolean" and not isinstance(value, bool):
        return f"{name} must be boolean, got {value!r}"
    if kind == "object":
        if not isinstance(value, dict):
            return f"{name} must be an object, got {value!r}"
        return _object_problem(name, value, spec.get("properties", {}), uuid_ids)
    if kind == "array":
        if not isinstance(value, list):
            return f"{name} must be an array, got {value!r}"
        for item in value:
            problem = _json_problem(f"{name}[]", item, spec.get("items", {}), uuid_ids)
            if problem:
                return problem
    return None


def _object_problem(
    name: str, value: dict[str, Any], fields: dict[str, Any], uuid_ids: bool
) -> str | None:
    for field_name, field_spec in fields.items():
        if field_spec.get("required") and field_name not in value:
            return f"{name}.{field_name} is required"
        if field_name in value:
            problem = _json_problem(f"{name}.{field_name}", value[field_name], field_spec, uuid_ids)
            if problem:
                return problem
    return None


def _query_problem(name: str, raw: str, spec: dict[str, Any], uuid_ids: bool) -> str | None:
    """A query or path value arrives as text; Immich converts it before it validates."""
    kind = spec.get("type")
    if kind in ("integer", "number"):
        shape = r"-?\d+" if kind == "integer" else r"-?\d+(?:\.\d+)?"
        if not re.fullmatch(shape, raw):
            return f"{name} must be {kind}, got {raw!r}"
        return _bounds_problem(name, float(raw), spec)
    if kind == "boolean" and raw not in ("true", "false"):
        return f"{name} must be true or false, got {raw!r}"
    if kind == "string":
        return _string_problem(name, raw, spec, uuid_ids)
    return None


def _endpoint(release: str, method: str, path: str) -> tuple[dict[str, Any], dict[str, str]] | None:
    for verb, pattern, key in _ROUTES[release]:
        match = pattern.match(path)
        if verb == method and match:
            return CONTRACT[release][key], match.groupdict()
    return None


def _undefined(names: Iterable[str], defined: Mapping[str, Any]) -> list[str]:
    # WHY refused: Immich drops a parameter its spec does not define without a word, so
    # sending one is always a bug: the request means less than the code thinks it does.
    return [f"{name} is not a parameter Immich defines" for name in names if name not in defined]


def _form_problems(fields: dict[str, Any], form: Mapping[str, str], uuid_ids: bool) -> list[str]:
    """A multipart upload's fields, text as the form carries them (the file part by name)."""
    problems = [
        f"{name} is required"
        for name, spec in fields.items()
        if spec["required"] and name not in form
    ]
    problems += _undefined(form, fields)
    return problems + [
        p
        for name, raw in form.items()
        if name in fields
        and fields[name].get("format") != "binary"
        and (p := _query_problem(name, raw, fields[name], uuid_ids))
    ]


def _parameter_problems(
    defined: dict[str, Any], given: Mapping[str, str], uuid_ids: bool
) -> list[str]:
    """Path or query values: required, defined, and of the declared type."""
    problems = [
        f"{name} is required"
        for name, spec in defined.items()
        if spec["required"] and name not in given
    ]
    problems += _undefined(given, defined)
    return problems + [
        p
        for name, raw in given.items()
        if name in defined and (p := _query_problem(name, raw, defined[name], uuid_ids))
    ]


def _body_problems(fields: dict[str, Any], body: Any, uuid_ids: bool) -> list[str]:
    if not isinstance(body, dict):
        return ["the request body must be a JSON object"]
    problems = [
        f"{name} is required"
        for name, spec in fields.items()
        if spec["required"] and name not in body
    ]
    problems += _undefined(body, fields)
    return problems + [
        p
        for name, value in body.items()
        if name in fields and (p := _json_problem(name, value, fields[name], uuid_ids))
    ]


def _release_problems(
    release: str,
    method: str,
    path: str,
    query: Mapping[str, str],
    body: Any,
    uuid_ids: bool,
    form: Mapping[str, str] | None = None,
) -> list[str]:
    found = _endpoint(release, method, path)
    if found is None:
        return []
    endpoint, path_values = found
    problems = _parameter_problems(endpoint["path"], path_values, uuid_ids)
    problems += _parameter_problems(endpoint["query"], query, uuid_ids)
    if "form" in endpoint and form is not None:
        problems += _form_problems(endpoint["form"], form, uuid_ids)
    if endpoint["body"] is not None:
        problems += _body_problems(endpoint["body"], body, uuid_ids)
    elif body:
        problems.append("this endpoint takes no request body")
    return problems


def request_problems(
    method: str,
    path: str,
    query: Mapping[str, str],
    body: Any,
    *,
    uuid_ids: bool = True,
    releases: tuple[str, ...] = RELEASES,
    form: Mapping[str, str] | None = None,
) -> list[str]:
    """What the named Immich releases would refuse in this request, as their 400s would say.

    A problem only some releases have is prefixed with them. `uuid_ids=False` relaxes the
    id checks for fixture libraries whose ids are readable names (the hermetic launch
    library); every other check still applies. `form` holds a multipart upload's text
    fields, with the file part present under its field name.
    """
    path = re.sub(r"^/api(?=/)", "", path)
    by_release = {
        r: _release_problems(r, method, path, query, body, uuid_ids, form) for r in releases
    }
    problems: list[str] = []
    for found in by_release.values():
        for problem in found:
            holders = [r for r, other in by_release.items() if problem in other]
            label = problem if len(holders) == len(releases) else f"{'/'.join(holders)}: {problem}"
            if label not in problems:
                problems.append(label)
    return problems


@dataclass
class ImmichWire:
    """An httpx transport that answers like Immich, refusing what Immich refuses.

    ``handler`` serves the requests that pass; ``violations`` keeps every one that did not,
    with the reason. Call ``assert_clean()`` at the end of a test.
    """

    handler: Callable[[httpx.Request], httpx.Response]
    uuid_ids: bool = True
    releases: tuple[str, ...] = RELEASES
    violations: list[str] = field(default_factory=list)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._serve)

    def _serve(self, request: httpx.Request) -> httpx.Response:
        body: Any = None
        if request.content and "json" in request.headers.get("content-type", ""):
            body = json.loads(request.content)
        problems = request_problems(
            request.method,
            request.url.path,
            dict(request.url.params),
            body,
            uuid_ids=self.uuid_ids,
            releases=self.releases,
        )
        if problems:
            self.violations.extend(f"{request.method} {request.url.path}: {p}" for p in problems)
            return httpx.Response(
                400, json={"message": problems, "error": "Bad Request", "statusCode": 400}
            )
        return self.handler(request)

    def assert_clean(self) -> None:
        assert self.violations == [], "requests the real Immich refuses:\n" + "\n".join(
            self.violations
        )
