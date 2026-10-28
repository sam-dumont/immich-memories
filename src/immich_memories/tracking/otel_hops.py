"""The hops a traced process makes, as spans: HTTP calls, store queries, child programs, routes.

Installed by `otel.setup()` only while exporting, and removed by `otel.shutdown()`. Each hop
records what it was and how it went, never what it carried:

- an HTTP call is named by its method and path with ids replaced, without its query string;
- a store query keeps its statement with the placeholders, never the bound values;
- a child program keeps its arguments with private paths cut to the file name and ids replaced;
- a web route is named by its template (`/api/v1/films/{film_id}`), health probes left out.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable, Sequence
from pathlib import PurePath
from typing import TYPE_CHECKING, Any

from opentelemetry.trace import Span

from immich_memories.logging_config import redact_secrets
from immich_memories.tracking import otel

if TYPE_CHECKING:
    from fastapi import FastAPI
    from opentelemetry.sdk.trace import ReadableSpan, TracerProvider

# UUIDs, and long hex or digit runs (hashes, numeric ids): what makes one path every path.
_IDS = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"|\b[0-9a-fA-F]{16,}\b|\b\d{6,}\b"
)
_HEALTH = "/health,/health/live,/health/ready"
# An absolute path of two or more parts outside a URL: `/home/x/store.db`, not `/api/v1`.
_PATHS = re.compile(
    r"(?<![\w:/.])(?:/(?:Users|home|var|private|tmp|data|mnt|srv|opt|root|Volumes)\b)(?:/[^\s/'\"]+)+"
)
# ffmpeg filter graphs run to kilobytes; a span keeps the head of each and of the list.
_ARGUMENTS = 64
_ARGUMENT_CHARACTERS = 512

_restore: list[Callable[[], None]] = []


def instrument(provider: TracerProvider) -> None:
    """Trace HTTP calls, store queries and child programs from here on."""
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    httpx_hops = HTTPXClientInstrumentor()
    httpx_hops.instrument(
        tracer_provider=provider,
        request_hook=_named_request,
        async_request_hook=_named_request_async,
        response_hook=_sized_response,
        async_response_hook=_sized_response_async,
    )
    _restore.append(httpx_hops.uninstrument)
    store_hops = SQLAlchemyInstrumentor()
    # The instrumentation names SQLAlchemy < 2.1 as its range; 2.1 kept the event API it uses.
    store_hops.instrument(tracer_provider=provider, enable_commenter=False, skip_dep_check=True)
    _restore.append(store_hops.uninstrument)
    _trace_children()


def uninstrument() -> None:
    """Put back what `instrument` changed."""
    while _restore:
        _restore.pop()()


def instrument_app(app: FastAPI, provider: TracerProvider) -> None:
    """Make each request to `app` a server span, joining the caller's trace when it sent one."""
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        excluded_urls=_HEALTH,
        server_request_hook=_named_route,
    )


def _named_route(span: Span, scope: dict[str, Any]) -> None:
    # The span is named by the route template; the raw path and query it also keeps do not.
    if not span.is_recording():
        return
    span.set_attribute("url.path", template(scope.get("path", "")))
    if scope.get("query_string"):
        span.set_attribute("url.query", "")


def without_paths(span: ReadableSpan) -> ReadableSpan:
    """`span` with every absolute path in its name and text attributes cut to the file name.

    The last line before export: an instrumentation that names a SQLite file, or an error that
    quotes a folder, would otherwise send a person's home layout to the collector.
    """
    from opentelemetry.sdk.trace import ReadableSpan

    name = _cut_paths(span.name)
    attributes = {
        key: _cut_paths(value) if isinstance(value, str) else value
        for key, value in (span.attributes or {}).items()
    }
    if name == span.name and attributes == dict(span.attributes or {}):
        return span
    return ReadableSpan(
        name=name,
        context=span.context,
        parent=span.parent,
        resource=span.resource,
        attributes=attributes,
        events=span.events,
        links=span.links,
        kind=span.kind,
        status=span.status,
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


def _cut_paths(text: str) -> str:
    return _PATHS.sub(lambda match: PurePath(match.group(0)).name, text)


def template(path: str) -> str:
    """`path` with every id replaced by `{id}`, so all calls of one kind share a name."""
    return _IDS.sub("{id}", path) or "/"


def _named_request(span: Span, request: Any) -> None:
    if not span.is_recording():
        return
    url = request.url
    path = template(url.path)
    method = request.method.decode() if isinstance(request.method, bytes) else request.method
    span.update_name(f"{method} {path}")
    port = f":{url.port}" if url.port else ""
    host = url.host.decode() if isinstance(url.host, bytes) else url.host
    scheme = url.scheme.decode() if isinstance(url.scheme, bytes) else url.scheme
    # Replaces what the instrumentation took from the raw URL: its query and its ids.
    span.set_attributes({"url.full": f"{scheme}://{host}{port}{path}", "url.template": path})


async def _named_request_async(span: Span, request: Any) -> None:
    _named_request(span, request)


def _sized_response(span: Span, request: Any, response: Any) -> None:
    import httpx

    if not span.is_recording():
        return
    if (size := httpx.Headers(response.headers).get("content-length")) is not None:
        span.set_attribute("http.response.body.size", int(size))


async def _sized_response_async(span: Span, request: Any, response: Any) -> None:
    _sized_response(span, request, response)


def _trace_children() -> None:
    """A span from each child program's start to its exit, on whichever thread started it."""
    popen = subprocess.Popen
    original_init, original_wait, original_poll = popen.__init__, popen.wait, popen.poll

    def init(self: subprocess.Popen, args: Any, *rest: Any, **options: Any) -> None:
        argv = [os.fspath(args)] if isinstance(args, str | bytes | os.PathLike) else list(args)
        program = PurePath(os.fsdecode(options.get("executable") or argv[0])).name
        span = otel.start(
            f"exec {program}",
            {"process.executable.name": program, "process.command_args": _arguments(argv)},
        )
        try:
            original_init(self, args, *rest, **options)
        except BaseException as error:
            otel.mark_failed(span, type(error).__name__, "the program could not start")
            otel.end(span)
            raise
        span.set_attribute("process.pid", self.pid)
        self.__dict__["_otel_span"] = span

    def wait(self: subprocess.Popen, *args: Any, **kwargs: Any) -> int:
        code = original_wait(self, *args, **kwargs)
        _exited(self, code)
        return code

    def poll(self: subprocess.Popen) -> int | None:
        code = original_poll(self)
        if code is not None:
            _exited(self, code)
        return code

    popen.__init__ = init  # type: ignore[method-assign]
    popen.wait = wait  # type: ignore[method-assign]
    popen.poll = poll  # type: ignore[method-assign]

    def restore() -> None:
        popen.__init__ = original_init  # type: ignore[method-assign]
        popen.wait = original_wait  # type: ignore[method-assign]
        popen.poll = original_poll  # type: ignore[method-assign]

    _restore.append(restore)


def _exited(process: subprocess.Popen, code: int) -> None:
    span = process.__dict__.pop("_otel_span", None)
    if span is None:
        return
    span.set_attribute("process.exit.code", code)
    if code != 0:
        otel.mark_failed(span, "ExitCode", f"the program exited with status {code}")
    otel.end(span)


def _arguments(argv: Sequence[Any]) -> list[str]:
    return [_argument(os.fsdecode(item)) for item in argv[:_ARGUMENTS]]


def _argument(value: str) -> str:
    """One argument without what would identify the library: its paths and its ids."""
    value = redact_secrets(value)
    if os.sep in value and not value.startswith("-"):
        # A path names a person's folders; the file name is what tells two steps apart.
        value = PurePath(value).name
    return _IDS.sub("{id}", value)[:_ARGUMENT_CHARACTERS]
