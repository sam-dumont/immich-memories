"""Report endpoint mounted behind the hosting application's authentication middleware."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from immich_memories.config_loader import Config, get_config
from immich_memories.db import open_store
from immich_memories.tracking.report_service import report_for_run

router = APIRouter(prefix="/api/v1/runs", tags=["reports"])


class ReportResponse(BaseModel):
    markdown: str
    has_flagged_photos: bool = False


def read_report(
    run_id: str,
    config: Annotated[Config, Depends(get_config)],
    include_flagged_captions: bool = False,
) -> ReportResponse:
    """Preview exactly what Copy report puts on the clipboard. Nothing is sent."""
    try:
        report = report_for_run(
            open_store(config), config, run_id, include_flagged_captions=include_flagged_captions
        )
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    return ReportResponse(
        markdown=report.markdown(),
        has_flagged_photos=bool(report.data.get("free_text", {}).get("flagged")),
    )


router.add_api_route(
    "/{run_id}/report", read_report, response_model=ReportResponse, methods=["GET"]
)
