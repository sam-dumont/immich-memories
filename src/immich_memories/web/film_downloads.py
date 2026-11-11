"""Download a run's local artifact or its recorded, delivered Immich original."""

import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from immich_memories.api.immich import ImmichAPIError
from immich_memories.config.loader import Config
from immich_memories.operations.shown_film_name import content_disposition
from immich_memories.tracking.models import DeliveryStatus, RunMetadata
from immich_memories.web.dependencies import current_config
from immich_memories.web.film_files import FILM_TYPES, local_film

FinishedFilmFetcher = Callable[[str, Path, int | None], Path]


def immich_finished_film(config: Annotated[Config, Depends(current_config)]) -> FinishedFilmFetcher:
    """Reuse the original-download client; credentials and endpoints stay server-side."""

    def fetch(asset_id: str, target: Path, size: int | None) -> Path:
        from immich_memories.api.sync_client import SyncImmichClient

        with SyncImmichClient(
            base_url=config.immich.url,
            api_key=config.immich.api_key,
            api_version=config.immich.api_version,
        ) as client:
            return client.download_asset(asset_id, target, expected_size_bytes=size)

    return fetch


def _shown_name(config: Config, record: RunMetadata, disk_name: str) -> str:
    """The name the browser saves: the film's language, falling back to the disk name."""
    from immich_memories.operations.shown_film_name import shown_film_name_for

    try:
        return shown_film_name_for(
            config, disk_name, memory_type=record.memory_type, person_name=record.person_name
        )
    except Exception:  # WHY: a download is never worth failing over its name
        return disk_name


def finished_film(config: Config, record: RunMetadata, fetch: FinishedFilmFetcher) -> FileResponse:
    path = local_film(record)
    cleanup = None
    name = path.name if path else "film.mp4"
    if path is None:
        asset_id = record.immich_asset_id or ""
        if record.delivery_status != DeliveryStatus.DELIVERED or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,64}", asset_id
        ):
            raise HTTPException(404, "This run has no downloadable film locally or in Immich.")
        folder = config.cache.cache_path / "web-film-downloads"
        folder.mkdir(parents=True, exist_ok=True)
        original = Path(record.output_path or "film.mp4")
        suffix = original.suffix.lower() if original.suffix.lower() in FILM_TYPES else ".mp4"
        name = original.name if original.suffix.lower() in FILM_TYPES else "film.mp4"
        with tempfile.NamedTemporaryFile(dir=folder, suffix=suffix, delete=False) as temporary:
            path = Path(temporary.name)
        try:
            fetch(asset_id, path, record.output_size_bytes or None)
            if path.stat().st_size == 0:
                raise ValueError("Empty original")
        except (ImmichAPIError, httpx.HTTPError, OSError, ValueError):
            path.unlink(missing_ok=True)
            raise HTTPException(
                502, "Immich could not provide this film. Retry or check the connection."
            ) from None
        cleanup = BackgroundTask(path.unlink, missing_ok=True)
    shown = _shown_name(config, record, name)
    return FileResponse(
        path,
        media_type=FILM_TYPES[path.suffix.lower()],
        # Starlette's own header drops the ASCII fallback for a name that is not ASCII.
        headers={
            "cache-control": "private, no-store",
            "content-disposition": content_disposition(shown, name),
        },
        background=cleanup,
    )
