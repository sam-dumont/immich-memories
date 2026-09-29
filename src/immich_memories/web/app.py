"""Mount the web client and its API on the FastAPI app web/server.py builds."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from immich_memories.api.immich import ImmichAPIError
from immich_memories.security import sanitize_error_message
from immich_memories.tracking import report_api
from immich_memories.web import (
    connection,
    cut,
    i18n,
    job_routes,
    library,
    media,
    pool,
    roster,
    runs,
    session,
    settings,
    suggestions,
)

CLIENT_PREFIX = "/app"
# `make web-build` writes the SvelteKit client here. It is not committed (#1580): the release
# wheel and the Docker image build it, and a source checkout builds it with `make dev`.
BUILT_CLIENT = Path(__file__).parent / "client"
# What a source checkout shows before the client is built, instead of a bare 404.
CLIENT_NOT_BUILT = (
    "<!doctype html><meta charset=utf-8><title>Immich Memories</title>"
    "<p>The web client is not built in this checkout. Run <code>make web-build</code> "
    "(or <code>make dev</code>), then reload.</p>"
)


async def _immich_refused(_request: Request, error: Exception) -> JSONResponse:
    # Immich down or refusing is the gateway's failure, not ours: say so, without a traceback.
    return JSONResponse({"detail": sanitize_error_message(str(error))}, status_code=502)


def mount_web(app: FastAPI, *, client_dir: Path = BUILT_CLIENT) -> None:
    """Add the /api/v1 routes and serve the client under /app."""
    app.include_router(runs.router)
    # The same builder `immich-memories report` prints from, typed for the client (#1428).
    app.include_router(report_api.router)
    app.include_router(cut.router)
    app.include_router(job_routes.router)
    app.include_router(library.router)
    app.include_router(pool.router)
    app.include_router(suggestions.router)
    app.include_router(roster.router)
    app.include_router(settings.router)
    app.include_router(connection.router)
    app.include_router(session.router)
    app.include_router(media.router)
    app.include_router(i18n.router)
    app.add_exception_handler(ImmichAPIError, _immich_refused)
    root = client_dir.resolve()

    async def client(path: str = "") -> Response:
        # Built assets are files; every other path is a client-side route for the app to draw.
        if path.startswith("_app/"):
            asset = (root / path).resolve()
            if asset.is_relative_to(root) and asset.is_file():
                return FileResponse(asset)
            return Response(status_code=404)
        index = root / "index.html"
        if index.is_file():
            return FileResponse(index)
        return HTMLResponse(CLIENT_NOT_BUILT, status_code=503)

    app.add_api_route(CLIENT_PREFIX, client, methods=["GET"], include_in_schema=False)
    app.add_api_route(
        f"{CLIENT_PREFIX}/{{path:path}}", client, methods=["GET"], include_in_schema=False
    )
