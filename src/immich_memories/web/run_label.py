"""Write a delivered film's label to Immich again from the run page, without rendering."""

from __future__ import annotations

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException

from immich_memories.api.film_relabel import RelabelStatus
from immich_memories.api.immich import ImmichAPIError
from immich_memories.config.loader import Config
from immich_memories.operations.film_relabel import RelabelRefused, relabel_run
from immich_memories.web.dependencies import current_config
from immich_memories.web.run_upload import ClientOpener, immich_opener
from immich_memories.web.schemas import RelabelAnswer

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])


@router.post("/{run_id}/label", response_model=RelabelAnswer)
def relabel_run_film(
    run_id: str,
    config: Annotated[Config, Depends(current_config)],
    open_client: Annotated[ClientOpener, Depends(immich_opener)],
) -> RelabelAnswer:
    """Write this run's current description and tags to the film Immich holds, and take off
    the app's own tags the label no longer has."""
    try:
        with open_client() as client:
            result = relabel_run(config, run_id, client=client)
    except RelabelRefused as refusal:
        raise HTTPException(refusal.status, str(refusal)) from refusal
    except (ImmichAPIError, httpx.HTTPError) as error:
        # The error text can carry the Immich address; the type says enough.
        raise HTTPException(
            502, f"Immich could not take the label ({type(error).__name__})"
        ) from error
    outcome = result.outcome
    if outcome.status is RelabelStatus.ASSET_GONE:
        raise HTTPException(
            409, "The film is no longer in Immich, so there is nothing to re-label."
        )
    if outcome.status is RelabelStatus.RIGHTS_MISSING:
        raise HTTPException(409, f"Immich refused: {outcome.detail}")
    return RelabelAnswer(
        status=outcome.status,
        detail=outcome.detail,
        removed_tags=list(outcome.removed),
        warnings=list(outcome.warnings),
    )
