"""Demucs HTTP boundary, sharing the application's local separator."""

import asyncio
import logging
import tempfile
from pathlib import Path
from zipfile import ZipFile

from fastapi import FastAPI, HTTPException, UploadFile
from starlette.background import BackgroundTask
from starlette.responses import FileResponse

from immich_memories.audio.generators.base import StemSeparator
from immich_memories.audio.generators.demucs_local import DemucsLocalBackend
from immich_memories_inference.limits import ENVELOPE_BYTES, RouteLimit

logger = logging.getLogger(__name__)
# Long stereo PCM soundtracks can exceed 64 MiB before separation.
MAX_AUDIO_BYTES = 256 * 1024 * 1024
STEM_NAMES = ("drums", "bass", "other", "vocals")
STEMS_PATH = "/audio/stems"


def stems_limit() -> RouteLimit:
    """One separation at a time, its upload capped before it is read.

    A second upload while one separates is told to retry rather than spooled to disk
    behind it: Demucs holds gigabytes, and a queue of soundtracks would hold more.
    """
    return RouteLimit(max_body_bytes=MAX_AUDIO_BYTES + ENVELOPE_BYTES, seats=1)


def register_audio(app: FastAPI, cache: Path, separator: StemSeparator | None) -> None:
    """Separate one upload and remove its job after the response is sent.

    Serialized by the seat `stems_limit` gives the route, taken before the body is read.
    """

    @app.post(STEMS_PATH)
    async def stems(file: UploadFile) -> FileResponse:
        payload = await file.read(MAX_AUDIO_BYTES + 1)
        if len(payload) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "audio is larger than 256 MiB")
        if not payload:
            raise HTTPException(400, "audio is empty")
        cache.mkdir(parents=True, exist_ok=True)
        scratch = tempfile.TemporaryDirectory(prefix="demucs-", dir=cache)
        try:
            work = asyncio.create_task(
                asyncio.to_thread(
                    lambda: asyncio.run(_separate(payload, Path(scratch.name), separator))
                )
            )
            try:
                archive = await asyncio.shield(work)
            except asyncio.CancelledError:
                # Keep the seat and scratch directory until native inference stops.
                await work
                raise
            return FileResponse(
                archive, media_type="application/zip", background=BackgroundTask(scratch.cleanup)
            )
        except BaseException:
            scratch.cleanup()
            raise


async def _separate(payload: bytes, folder: Path, separator: StemSeparator | None) -> Path:
    backend = separator or DemucsLocalBackend()
    source = folder / "input.audio"
    source.write_bytes(payload)
    try:
        stems = await backend.separate_stems(source, folder)
        archive = folder / "stems.zip"
        with ZipFile(archive, "w") as output:
            for name in STEM_NAMES:
                output.write(getattr(stems, name), f"{name}.wav")
        return archive
    except Exception as error:
        logger.warning("Demucs separation failed (%s)", type(error).__name__)
        raise HTTPException(503, "Demucs separation unavailable") from None
    finally:
        if isinstance(backend, DemucsLocalBackend):
            backend.release()
