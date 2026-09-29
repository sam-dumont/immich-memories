"""Report endpoint mounted behind the hosting application's authentication middleware."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from immich_memories.config_loader import Config, get_config
from immich_memories.db import open_store
from immich_memories.tracking.report import RunReport
from immich_memories.tracking.report_service import report_for_run

router = APIRouter(prefix="/api/v1/runs", tags=["reports"])


class ReportResponse(BaseModel):
    markdown: str
    has_flagged_photos: bool = False


def report_config() -> Config:
    """The loaded config, without get_config's reload flag becoming a public query parameter."""
    return get_config()


def _report(config: Config, run_id: str, include_flagged_captions: bool) -> RunReport:
    try:
        return report_for_run(
            open_store(config), config, run_id, include_flagged_captions=include_flagged_captions
        )
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


def read_report(
    run_id: str,
    config: Annotated[Config, Depends(report_config)],
    include_flagged_captions: bool = False,
) -> ReportResponse:
    """Preview exactly what Copy report puts on the clipboard. Nothing is sent."""
    report = _report(config, run_id, include_flagged_captions)
    return ReportResponse(
        markdown=report.markdown(),
        has_flagged_photos=bool(report.data.get("free_text", {}).get("flagged")),
    )


def download_report(
    run_id: str,
    config: Annotated[Config, Depends(report_config)],
    include_flagged_captions: bool = False,
) -> Response:
    """The ZIP `report --bundle` writes: report.md, report.json and run.log, all redacted."""
    bundle = _report(config, run_id, include_flagged_captions).bundle()
    # A fixed name: the file may be attached to an issue, and a run id dates the run.
    disposition = 'attachment; filename="immich-memories-report.zip"'
    return Response(
        bundle, media_type="application/zip", headers={"content-disposition": disposition}
    )


router.add_api_route(
    "/{run_id}/report", read_report, response_model=ReportResponse, methods=["GET"]
)
router.add_api_route(
    "/{run_id}/report/bundle",
    download_report,
    methods=["GET"],
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}}, 404: {}},
)
