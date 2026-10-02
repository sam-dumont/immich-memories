"""Inspect an installation's acquisition plan; downloads require a separate explicit job."""

import hashlib
import hmac
import json
from contextlib import suppress
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from immich_memories.analysis.editorial_preparation_detectors import (
    DETECTOR_SNAPSHOTS,
    DOCLING_REVISION,
)
from immich_memories.config_loader import Config
from immich_memories.model_acquisition import acquisition_plan
from immich_memories.security import credential_fingerprint
from immich_memories.web.dependencies import current_config
from immich_memories.web.job_routes import (
    JobView,
    _busy,
    _config_flag,
    _view,
    cli_executable,
    job_runner,
)
from immich_memories.web.jobs import JobBusy, JobRunner
from immich_memories.web.schemas import ModelAcquisitionStatus, ModelArtifactView, ModelFetchRequest

router = APIRouter(prefix="/api/v1/models", tags=["jobs"])


def acquisition_id(config: Config) -> str:
    """Bind consent to the actual acquisition parameters, without exposing mirror secrets."""
    parameters: list[object] = [
        (item.url, str(item.destination), item.artifact.sha256, item.size)
        for item in acquisition_plan(config)
    ]
    if config.editorial.detectors_enabled:
        parameters.append((DETECTOR_SNAPSHOTS, config.editorial.preparation.detector_cache_dir))
    # A short signed-URL credential must not become a cheap guessing oracle in the browser.
    return credential_fingerprint(json.dumps(parameters, sort_keys=True))


@router.get("", response_model=ModelAcquisitionStatus)
def model_status(config: Annotated[Config, Depends(current_config)]) -> ModelAcquisitionStatus:
    artifacts = []
    for item in acquisition_plan(config):
        try:
            with item.destination.open("rb") as source:
                ready = hashlib.file_digest(source, "sha256").hexdigest() == item.artifact.sha256
        except OSError:
            ready = False
        artifacts.append(
            ModelArtifactView(
                label=item.artifact.label,
                host=urlsplit(item.url).hostname or "",
                size=item.size,
                sha256=item.artifact.sha256,
                ready=ready,
            )
        )
    if config.editorial.detectors_enabled:
        for repo, revision, files in DETECTOR_SNAPSHOTS:
            ready = False
            with suppress(ImportError):
                from huggingface_hub import try_to_load_from_cache

                ready = all(
                    isinstance(
                        try_to_load_from_cache(
                            repo,
                            filename,
                            revision=revision,
                            cache_dir=config.editorial.preparation.detector_cache_dir or None,
                        ),
                        str,
                    )
                    for filename in files
                )
            artifacts.append(
                ModelArtifactView(
                    label=repo,
                    host="huggingface.co",
                    size="16.8 MB"
                    if revision == DOCLING_REVISION
                    else "Pinned snapshot; size not recorded",
                    revision=revision,
                    ready=ready,
                )
            )
    return ModelAcquisitionStatus(
        plan_id=acquisition_id(config),
        ready=all(item.ready for item in artifacts),
        artifacts=artifacts,
    )


@router.post("/fetch", response_model=JobView, status_code=202, responses={409: {}})
def fetch_models(
    request: ModelFetchRequest,
    config: Annotated[Config, Depends(current_config)],
    runner: Annotated[JobRunner, Depends(job_runner)],
    executable: Annotated[str, Depends(cli_executable)],
) -> JobView | JSONResponse:
    """Only this explicit authenticated request authorizes the public CLI download job."""
    if not hmac.compare_digest(request.plan_id, acquisition_id(config)):
        raise HTTPException(
            409, "Model list changed. Review the refreshed list before downloading."
        )
    config_flag = _config_flag()
    argv = [executable, *(["--config", str(config_flag)] if config_flag else []), "models", "fetch"]
    try:
        job = runner.start("models", argv, meta={"shown": "immich-memories models fetch"})
    except JobBusy as busy:
        return _busy(busy, config)
    return _view(config, job)
