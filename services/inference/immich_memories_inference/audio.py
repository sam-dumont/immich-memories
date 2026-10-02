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

logger = logging.getLogger(__name__)
# Long stereo PCM soundtracks can exceed 64 MiB before separation.
MAX_AUDIO_BYTES = 256 * 1024 * 1024
STEM_NAMES = ("drums", "bass", "other", "vocals")


def register_audio(app: FastAPI, cache: Path, separator: StemSeparator | None) -> None:
    """Serialize audio inference and remove each job after its response is sent."""
    lock = asyncio.Lock()

    @app.post("/audio/stems")
    async def stems(file: UploadFile) -> FileResponse:
        payload = await file.read(MAX_AUDIO_BYTES + 1)
        if len(payload) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "audio is larger than 256 MiB")
        if not payload:
            raise HTTPException(400, "audio is empty")
        cache.mkdir(parents=True, exist_ok=True)
        scratch = tempfile.TemporaryDirectory(prefix="demucs-", dir=cache)
        try:
            async with lock:
                work = asyncio.create_task(
                    asyncio.to_thread(
                        lambda: asyncio.run(_separate(payload, Path(scratch.name), separator))
                    )
                )
                try:
                    archive = await asyncio.shield(work)
                except asyncio.CancelledError:
                    # Keep the lock and scratch directory until native inference stops.
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
