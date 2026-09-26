"""Mount the web client and its API on a FastAPI app: NiceGUI's today, a plain one later."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response

from immich_memories.web import cut, i18n, media, runs

CLIENT_PREFIX = "/app"
# `make web-build` writes the SvelteKit client here, so an install needs no Node.
BUILT_CLIENT = Path(__file__).parent / "client"


def mount_web(app: FastAPI, *, client_dir: Path = BUILT_CLIENT) -> None:
    """Add the /api/v1 routes and serve the client under /app."""
    app.include_router(runs.router)
    app.include_router(cut.router)
    app.include_router(media.router)
    app.include_router(i18n.router)
    root = client_dir.resolve()

    async def client(path: str = "") -> Response:
        # Built assets are files; every other path is a client-side route for the app to draw.
        if path.startswith("_app/"):
            asset = (root / path).resolve()
            if asset.is_relative_to(root) and asset.is_file():
                return FileResponse(asset)
            return Response(status_code=404)
        index = root / "index.html"
        return FileResponse(index) if index.is_file() else Response(status_code=404)

    app.add_api_route(CLIENT_PREFIX, client, methods=["GET"], include_in_schema=False)
    app.add_api_route(
        f"{CLIENT_PREFIX}/{{path:path}}", client, methods=["GET"], include_in_schema=False
    )
