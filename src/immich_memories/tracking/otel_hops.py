"""The hops a traced process makes, as spans: HTTP calls, store queries, child programs, routes.

Installed by `otel.setup()` only while exporting, and removed by `otel.shutdown()`. Each hop
records what it was and how it went, never what it carried:

- an HTTP call is named by its method and path with ids and map tile coordinates replaced,
  without its query string;
- a store query keeps its statement with the placeholders, never the bound values;
- a child program keeps its arguments as `trace_redaction.arguments` leaves them: private paths
  cut to the file name, ids replaced, names and free text replaced unless content is captured;
- a web route is named by its template (`/api/v1/films/{film_id}`), and its path is that
  template, so a name in a segment (`/api/v1/accounts/{name}/people`) stays home; health probes
  are left out.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from pathlib import PurePath
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

from opentelemetry.trace import Span

from immich_memories.tracking import otel
from immich_memories.tracking.trace_redaction import IDS, arguments, cut_paths

if TYPE_CHECKING:
    from fastapi import FastAPI
    from opentelemetry.sdk.trace import TracerProvider

# A path segment of digits alone: a map tile's zoom, column and row (`/14/8392/5467.png`), which
# say where a trip went or where home is.
_NUMBERS = re.compile(r"(?<=/)\d+(?=[/.@]|$)")
# A request as a browser span names it: `GET /api/v1/...`, a bare path, or a whole URL.
_REQUEST = re.compile(r"(?P<method>[A-Z]+ )?(?P<target>https?://\S+|/\S*)")
# Health probes, the route the web client sends its own spans through, and static files: the
# client's bundle is thirty requests a page load that say nothing the page's own spans do not.
_UNTRACED = "/health,/health/live,/health/ready,/api/v1/telemetry,/app/_app/,/static/,/favicon.ico"

_restore: list[Callable[[], None]] = []
# The traced apps, whose route templates name the requests made to them.
_apps: list[FastAPI] = []


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
    _apps.clear()


def instrument_app(app: FastAPI, provider: TracerProvider) -> None:
    """Make each request to `app` a server span, joining the caller's trace when it sent one."""
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    _apps.append(app)
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        excluded_urls=_UNTRACED,
        server_request_hook=_named_route,
        # The ASGI message spans (three per request) say nothing the route span does not.
        exclude_spans=["receive", "send"],
    )


def _named_route(span: Span, scope: dict[str, Any]) -> None:
    # The span is named by the route template; the raw path and query it also keeps do not.
    if not span.is_recording():
        return
    span.set_attribute("url.path", route_template(scope.get("path", "")))
    if scope.get("query_string"):
        span.set_attribute("url.query", "")


def scrub(text: str) -> str:
    """Text from outside the app (a browser span) without query strings, ids, names or paths."""
    if request := _REQUEST.fullmatch(text):
        parts = urlsplit(request["target"])
        path = route_template(parts.path)
        text = (request["method"] or "") + urlunsplit((parts.scheme, parts.netloc, path, "", ""))
    return IDS.sub("{id}", cut_paths(text))


def template(path: str) -> str:
    """`path` with every id and tile coordinate replaced by `{id}`: one name per kind of call."""
    return _NUMBERS.sub("{id}", IDS.sub("{id}", path)) or "/"


def route_template(path: str) -> str:
    """The template of the traced app's route `path` matches, else `template(path)`.

    A route's parameters are not all ids: an account name or a group label is a segment too.
    """
    from starlette.convertors import PathConvertor
    from starlette.routing import Route

    for app in _apps:
        for route in app.routes:
            if (
                isinstance(route, Route)
                and route.param_convertors
                and not any(isinstance(c, PathConvertor) for c in route.param_convertors.values())
                and route.path_regex.match(path)
            ):
                return route.path_format
    return template(path)


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
            {"process.executable.name": program, "process.command_args": arguments(argv)},
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
