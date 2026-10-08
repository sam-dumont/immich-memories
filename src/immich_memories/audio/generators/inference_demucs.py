"""Stem separation through the owned inference service."""

import logging
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import IO, Any
from zipfile import BadZipFile, ZipFile

import httpx

from immich_memories.audio.generators.base import StemSeparator
from immich_memories.audio.music_generator_models import MusicStems

logger = logging.getLogger(__name__)
MAX_STEM_BYTES = 256 * 1024 * 1024
# Four stems plus the ZIP envelope. Larger valid archives spill to disk after 8 MiB.
_MAX_RESPONSE_BYTES = 4 * MAX_STEM_BYTES + 64 * 1024


class InferenceDemucs:
    """Upload one full mix and return the four fixed-name stem files."""

    def __init__(self, base_url: str, fallback: StemSeparator | None = None):
        self.base_url = base_url.rstrip("/")
        self.fallback = fallback

    @property
    def name(self) -> str:
        return "Demucs (inference service)"

    async def is_available(self) -> bool:
        """Attempt the configured service; the pipeline handles a failed request."""
        return True

    async def separate_stems(
        self, audio_path: Path, output_dir: Path, progress_callback: Any | None = None
    ) -> MusicStems:
        """Recover locally when allowed, without exposing service errors in logs."""
        try:
            return await self._remote_stems(audio_path, output_dir)
        except (httpx.HTTPError, OSError, ValueError, KeyError, BadZipFile):
            if self.fallback is None:
                raise
            logger.warning("Inference Demucs unavailable; separating stems locally")
            return await self.fallback.separate_stems(audio_path, output_dir, progress_callback)

    async def _remote_stems(self, audio_path: Path, output_dir: Path) -> MusicStems:
        with SpooledTemporaryFile(max_size=8 * 1024 * 1024) as payload:
            async with httpx.AsyncClient(timeout=600) as client:
                with audio_path.open("rb") as audio:
                    async with client.stream(
                        "POST",
                        f"{self.base_url}/audio/stems",
                        files={"file": ("input.wav", audio, "audio/wav")},
                    ) as response:
                        await _copy_stems_response(response, payload)
            payload.seek(0)
            with ZipFile(payload) as archive:
                return self._extract_stems(archive, output_dir)

    @staticmethod
    def _extract_stems(archive: ZipFile, output_dir: Path) -> MusicStems:
        output_dir.mkdir(parents=True, exist_ok=True)
        paths = {}
        for name in ("drums", "bass", "other", "vocals"):
            entry = archive.getinfo(f"{name}.wav")
            if entry.file_size > MAX_STEM_BYTES:
                raise ValueError("Inference stem exceeds 256 MiB")
            paths[name] = output_dir / f"{name}.wav"
            paths[name].write_bytes(archive.read(entry))
        return MusicStems(**paths)


async def _copy_stems_response(response: httpx.Response, payload: IO[bytes]) -> None:
    response.raise_for_status()
    if int(response.headers.get("content-length", 0)) > _MAX_RESPONSE_BYTES:
        raise ValueError("Inference stems response exceeds the expected size")
    downloaded = 0
    async for chunk in response.aiter_bytes():
        downloaded += len(chunk)
        if downloaded > _MAX_RESPONSE_BYTES:
            raise ValueError("Inference stems response exceeds the expected size")
        payload.write(chunk)
