"""The existing OpenAI-compatible caption contract on the worker's one address."""

import asyncio

import httpx
from fastapi import FastAPI, HTTPException, Request
from starlette.responses import StreamingResponse

from immich_memories_inference.caption_runtime import CaptionRuntime, CaptionUnavailable

MAX_CAPTION_BYTES = 32 * 1024 * 1024


def register_captions(app: FastAPI, captions: CaptionRuntime) -> None:
    @app.get("/v1/{path:path}")
    @app.post("/v1/{path:path}")
    async def caption(path: str, request: Request):
        if ".." in path.split("/") or "\\" in path:
            raise HTTPException(400, "Invalid caption endpoint")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_CAPTION_BYTES:
                raise HTTPException(413, "Caption request is larger than 32 MiB")
        startup = asyncio.create_task(asyncio.to_thread(captions.start))
        try:
            await asyncio.shield(startup)
        except asyncio.CancelledError:
            await startup
            raise
        except CaptionUnavailable:
            raise HTTPException(503, "Bundled caption runtime is unavailable") from None
        # Render bearer tokens and client cookies belong to this worker, never
        # to the model process. Only the content negotiation headers cross it.
        headers = {
            name: request.headers[name]
            for name in ("content-type", "accept")
            if name in request.headers
        }
        client: httpx.AsyncClient = app.state.caption_http
        target = f"{captions.base_url}/v1/{path}"
        outgoing = client.build_request(
            request.method,
            target,
            params=request.query_params,
            headers=headers,
            content=bytes(body),
        )
        try:
            response = await client.send(outgoing, stream=True)
        except httpx.HTTPError:
            raise HTTPException(503, "Bundled caption runtime is unavailable") from None

        async def stream():
            try:
                async for chunk in response.aiter_raw():
                    yield chunk
            finally:
                await response.aclose()

        return StreamingResponse(
            stream(),
            status_code=response.status_code,
            headers={
                name: response.headers[name]
                for name in ("content-type", "content-encoding", "cache-control")
                if name in response.headers
            },
        )
