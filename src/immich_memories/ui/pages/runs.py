"""Run history reads the same database, run index and storyboard as the terminal."""

from nicegui import ui

from immich_memories.config import get_config
from immich_memories.operations.auto_output import output_log_path
from immich_memories.operations.run_index import attempt_dir_for_run
from immich_memories.operations.storyboard import read_storyboard, storyboard_lines
from immich_memories.tracking import RunDatabase
from immich_memories.ui.i18n import tr


def render_run_details(run_id: str) -> None:
    """One durable run: status, timings, delivery, its saved cut and any child output."""
    record = RunDatabase(get_config().cache.database_path).get_run(run_id)
    ui.link(tr("Back to runs"), "/app/runs")
    if record is None:
        ui.label(tr("Run not found. It may have been removed."))
        return
    config = get_config()
    ui.label(record.run_id).classes("text-lg font-semibold")
    ui.label(
        f"{tr(record.status).capitalize()} · {record.created_at:%Y-%m-%d %H:%M} · {record.source}"
    )
    ui.label(
        tr(
            "{clips_selected} pictures selected · {total_duration_seconds:.1f}s recorded run time",
            clips_selected=record.clips_selected,
            total_duration_seconds=record.total_duration_seconds,
        )
    )
    if record.output_path:
        ui.label(tr("Saved to: {output_path}", output_path=record.output_path)).classes("break-all")
    ui.label(tr("Immich delivery: {value}", value=record.delivery_status.value.replace("_", " ")))
    for warning in record.warnings:
        ui.label(warning).classes("text-sm")
    for phase in record.phases:
        ui.label(
            tr(
                "{value}: {duration_seconds:.1f}s",
                value=phase.phase_name.replace("_", " "),
                duration_seconds=phase.duration_seconds,
            )
        )
        for error in phase.errors:
            ui.label(str(error)).classes("whitespace-pre-wrap break-all text-sm")
    attempt = attempt_dir_for_run(config.cache.cache_path, record.run_id)
    board = read_storyboard(attempt) if attempt else None
    if board:
        with ui.expansion(tr("Read the cut"), value=True).classes("w-full"):
            ui.label(board.thesis)
            ui.label(board.summary_label)
            ui.label("\n".join(storyboard_lines(board))).classes(
                "whitespace-pre-wrap font-mono text-sm"
            )
    else:
        ui.label(tr("No saved cut is available for this run."))
    if record.automation_attempt_id:
        # `generate --automation-attempt-id` accepts any string, and only an id
        # automation itself opened addresses a transcript.
        try:
            log = output_log_path(config.cache.cache_path, record.automation_attempt_id)
        except ValueError:
            log = None
        if log is not None and log.is_file():
            ui.button(tr("Download child output"), on_click=lambda: ui.download.file(log))
        else:
            ui.label(tr("No child output was retained for this run."))
