"""Send a finished run's film to Immich without rendering it again."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from immich_memories.api.immich import ImmichAPIError
from immich_memories.config_loader import Config
from immich_memories.db import open_store
from immich_memories.tracking import RunDatabase
from immich_memories.web.dependencies import current_config
from immich_memories.web.film_files import local_film
from immich_memories.web.render_capabilities import CapabilitiesReader, immich_render_capabilities

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])


class UploadRefused(Exception):
    """The film cannot be sent; `status` is the HTTP answer the page shows."""

    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


class UploadRequest(BaseModel):
    album: str | None = None


class UploadedFilm(BaseModel):
    asset_id: str
    asset_url: str | None
    album: str | None
    warnings: list[str]


def upload_finished_film(
    config: Config,
    run_id: str,
    album: str | None,
    *,
    missing_upload: tuple[str, ...],
    client: Any,
) -> UploadedFilm:
    """Upload the run's film on disk and record the asset on the run.

    Refuses, with the reason, an unknown run, a cut never rendered, a film that is gone, or a key without upload scope.
    """
    db = RunDatabase(open_store(config))
    record = db.get_run(run_id)
    if record is None:
        raise UploadRefused("Run not found. It may have been removed.", 404)
    film = local_film(record) if record.status == "completed" else None
    if film is None and record.status == "completed" and not record.output_path:
        # A kept cut is a completed run with no film: it never reached an encode.
        raise UploadRefused(
            "This run was never rendered, so there is no film to upload. "
            f"Run `immich-memories runs render {run_id}` first, then upload the new run it makes."
        )
    if film is None:
        raise UploadRefused(
            "This run's film file is gone, so there is nothing to upload. Render it again first."
        )
    if missing_upload:
        raise UploadRefused("Upload unavailable: the key lacks " + ", ".join(missing_upload))
    album_name = album.strip() if album and album.strip() else config.upload.album_name
    result = client.upload_memory(video_path=film, album_name=album_name)
    asset_id = result.get("asset_id")
    warnings = [str(w) for w in result.get("warnings", [])]
    if result.get("delivery_complete") is False or not asset_id:
        raise UploadRefused(
            "; ".join(warnings) or "Immich did not accept the upload; the local film is kept.",
            502,
        )
    saved = db.mark_uploaded_later(run_id, asset_id, album=album_name)
    return UploadedFilm(
        asset_id=asset_id,
        asset_url=config.immich.asset_url(saved.immich_asset_id),
        album=album_name,
        warnings=warnings,
    )


ClientOpener = Callable[[], AbstractContextManager[Any]]


def immich_opener(config: Annotated[Config, Depends(current_config)]) -> ClientOpener:
    """Open the Immich client only inside the handler, after the body has been validated."""

    def open_client() -> AbstractContextManager[Any]:
        from immich_memories.api.sync_client import SyncImmichClient

        return SyncImmichClient(
            base_url=config.immich.url,
            api_key=config.immich.api_key,
            api_version=config.immich.api_version,
        )

    return open_client


@router.post("/{run_id}/upload", response_model=UploadedFilm)
def upload_run_film(
    run_id: str,
    request: UploadRequest,
    config: Annotated[Config, Depends(current_config)],
    read_missing: Annotated[CapabilitiesReader, Depends(immich_render_capabilities)],
    open_client: Annotated[ClientOpener, Depends(immich_opener)],
) -> UploadedFilm:
    """Upload this run's existing film, optionally into an album, under the render-time key check."""
    try:
        with open_client() as client:
            return upload_finished_film(
                config, run_id, request.album, missing_upload=read_missing(), client=client
            )
    except UploadRefused as refusal:
        raise HTTPException(refusal.status, str(refusal)) from refusal
    except (ImmichAPIError, httpx.HTTPError) as error:
        raise HTTPException(502, f"Immich could not take the upload: {error}") from error
