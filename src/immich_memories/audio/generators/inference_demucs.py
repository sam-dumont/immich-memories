"""Stem separation through the owned inference service."""

import logging
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

import httpx

from immich_memories.audio.generators.base import StemSeparator
from immich_memories.audio.music_generator_models import MusicStems

logger = logging.getLogger(__name__)
MAX_STEM_BYTES = 256 * 1024 * 1024


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
        async with httpx.AsyncClient(timeout=600) as client:
            with audio_path.open("rb") as audio:
                response = await client.post(
                    f"{self.base_url}/audio/stems",
                    files={"file": ("input.wav", audio, "audio/wav")},
                )
            response.raise_for_status()
        output_dir.mkdir(parents=True, exist_ok=True)
        paths = {}
        with ZipFile(BytesIO(response.content)) as archive:
            for name in ("drums", "bass", "other", "vocals"):
                entry = archive.getinfo(f"{name}.wav")
                if entry.file_size > MAX_STEM_BYTES:
                    raise ValueError("Inference stem exceeds 256 MiB")
                paths[name] = output_dir / f"{name}.wav"
                paths[name].write_bytes(archive.read(entry))
        return MusicStems(**paths)
