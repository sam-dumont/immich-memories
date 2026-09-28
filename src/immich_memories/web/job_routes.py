"""Start a cut or a render from the browser, follow it, cancel it, and play the film it made."""

from __future__ import annotations

import asyncio
import json
import shlex
import shutil
import sys
from collections.abc import AsyncIterator
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from immich_memories.config import get_config_path
from immich_memories.config_loader import Config
from immich_memories.db import open_store
from immich_memories.operations.cut_progress import (
    live_progress_of,
    read_latest_attempt,
    recent_pictures_of,
)
from immich_memories.operations.run_index import attempt_dir_for_run, run_id_for_attempt
from immich_memories.tracking import RunDatabase
from immich_memories.web.brief import CutBrief
from immich_memories.web.dependencies import current_config
from immich_memories.web.jobs import JobBusy, JobRunner
from immich_memories.web.schemas import Job, JobProgress

router = APIRouter(prefix="/api/v1", tags=["jobs"])


@lru_cache(maxsize=4)
def _runner(cache: Path) -> JobRunner:
    return JobRunner(cache)


def job_runner(config: Annotated[Config, Depends(current_config)]) -> JobRunner:
    """One runner per cache: every page of this server sees the same jobs."""
    return _runner(config.cache.cache_path)


def cli_executable() -> str:
    """The `immich-memories` command of this very installation."""
    beside = Path(sys.executable).parent / "immich-memories"
    return str(beside) if beside.is_file() else shutil.which("immich-memories") or "immich-memories"


def _config_flag() -> Path | None:
    path = get_config_path()
    return path if path.is_file() else None


class RenderOptions(BaseModel):
    """`runs render`'s flags; None keeps the CLI's own default."""

    revision: int | None = None
    title: str | None = None
    subtitle: str | None = None
    transition: str | None = None
    resolution: str | None = None
    orientation: str | None = None
    format: str | None = None
    quality: str | None = None
    scale_mode: str | None = None
    # "none", "auto" (as configured), or the id of a previewed or uploaded track.
    music: str = "auto"
    music_volume: float | None = None
    add_date: bool = False
    add_place: bool = False
    privacy_mode: bool = False
    upload_to_immich: bool = False
    album: str | None = None
    # None leaves the naming to generate's own rule; True/False is --llm-title/--no-llm-title.
    llm_title: bool | None = None

    def flags(self, music_path: Path | None = None) -> list[str]:
        """`runs render`'s flags; a chosen track travels as the server's own path to it."""
        valued = (
            "revision",
            "title",
            "subtitle",
            "transition",
            "resolution",
            "orientation",
            "format",
            "quality",
            "scale_mode",
            "music_volume",
            "album",
        )
        switches = ("add_date", "add_place", "privacy_mode", "upload_to_immich")
        return [
            *(
                f"--{n.replace('_', '-')}={getattr(self, n)}"
                for n in valued
                if getattr(self, n) is not None
            ),
            *(f"--{n.replace('_', '-')}" for n in switches if getattr(self, n)),
            *(["--no-music"] if self.music == "none" else []),
            *([f"--music={music_path}"] if music_path else []),
            *(
                []
                if self.llm_title is None
                else ["--llm-title" if self.llm_title else "--no-llm-title"]
            ),
        ]


class JobView(Job):
    command: str
    progress: JobProgress


def _cut_root(config: Config, job_id: str) -> Path | None:
    runs = config.cache.cache_path / "editorial-runs"
    return next(iter(sorted(runs.glob(f"web-{job_id}*"))), None) if runs.is_dir() else None


def _cut_progress(config: Config, job: Job) -> JobProgress:
    record = read_latest_attempt(_cut_root(config, job.id))
    if record is None:
        return JobProgress(label="Preparing the pool")
    live = live_progress_of(record)
    return JobProgress(
        label=str(record.get("stage") or ""),
        stage_name=live.label if live else str((record.get("progress") or {}).get("label") or ""),
        phase=live.phase if live else "",
        done=live.done if live else None,
        total=live.total if live else None,
        fraction=live.fraction if live else None,
        remaining_seconds=live.remaining_seconds if live and live.remaining_label else None,
        recent_asset_ids=list(recent_pictures_of(record)),
    )


def _render_progress(job: Job) -> JobProgress:
    path = Path(str(job.meta.get("progress_file") or ""))
    try:
        record: dict[str, Any] = json.loads(path.read_text()) if path.is_file() else {}
    except ValueError:
        record = {}
    return JobProgress(
        label=str(record.get("message") or "Preparing the render"),
        phase=str(record.get("phase") or ""),
        fraction=record.get("fraction"),
    )


def _view(config: Config, job: Job) -> JobView:
    if job.kind == "cut":
        progress = _cut_progress(config, job)
    elif job.kind in {"render", "music"}:
        progress = _render_progress(job)
    else:
        progress = JobProgress(label="Reading the library")
    shown = str(job.meta.get("shown") or shlex.join(job.argv))
    return JobView(**job.model_dump(), command=shown, progress=progress)


def _busy(busy: JobBusy, config: Config) -> JSONResponse:
    return JSONResponse(
        {"detail": str(busy), "job": _view(config, busy.job).model_dump(mode="json")},
        status_code=409,
    )


class ShownCommand(BaseModel):
    command: str


@router.post("/cuts/command", response_model=ShownCommand)
def cut_command(brief: CutBrief) -> ShownCommand:
    """The command this brief stands for, as the page offers it to copy."""
    return ShownCommand(command=brief.shown_command())


def _start_cut(
    brief: CutBrief, config: Config, runner: JobRunner, executable: str
) -> JobView | JSONResponse:
    from uuid import uuid4

    job_id = uuid4().hex
    output = config.cache.cache_path / "web-jobs" / f"web-{job_id}.mp4"

    def found_run(job: Job) -> Job:
        record = read_latest_attempt(_cut_root(config, job.id))
        attempt = Path(record["directory"]) if record else None
        return job.model_copy(
            update={"result_run_id": run_id_for_attempt(attempt) if attempt else None}
        )

    try:
        job = runner.start(
            "cut",
            brief.argv(executable=executable, config=_config_flag(), output=output),
            meta={"shown": brief.shown_command(), "brief": brief.model_dump_json()},
            on_finish=found_run,
            job_id=job_id,
        )
    except JobBusy as busy:
        return _busy(busy, config)
    return _view(config, job)


@router.post("/cuts", response_model=JobView, status_code=202, responses={409: {}})
def start_cut(
    brief: CutBrief,
    config: Annotated[Config, Depends(current_config)],
    runner: Annotated[JobRunner, Depends(job_runner)],
    executable: Annotated[str, Depends(cli_executable)],
) -> JobView | JSONResponse:
    """Cut this brief with `generate --no-render`; the job ends with the run the cut became."""
    return _start_cut(brief, config, runner, executable)


@router.post("/runs/{run_id}/renders", response_model=JobView, status_code=202, responses={409: {}})
def start_render(
    run_id: str,
    options: RenderOptions,
    config: Annotated[Config, Depends(current_config)],
    runner: Annotated[JobRunner, Depends(job_runner)],
    executable: Annotated[str, Depends(cli_executable)],
) -> JobView | JSONResponse:
    """Render this run's cut, or one revision of it, with `runs render`."""
    attempt = attempt_dir_for_run(run_id, store=open_store(config))
    if attempt is None:
        raise HTTPException(404, "This run left no saved cut.")
    from uuid import uuid4

    job_id = uuid4().hex
    progress_file = runner.progress_path(job_id)
    config_flag = _config_flag()
    track = None if options.music in {"none", "auto"} else music_file(config, options.music)
    if options.music not in {"none", "auto"} and track is None:
        raise HTTPException(404, "That music track is gone; preview or upload it again.")
    argv = [
        executable,
        *(["--config", str(config_flag)] if config_flag else []),
        "runs",
        "render",
        run_id,
        *options.flags(track),
        "--progress-file",
        str(progress_file),
    ]
    shown = shlex.join(["immich-memories", "runs", "render", run_id, *options.flags(track)])

    def found_film(job: Job) -> Job:
        return job.model_copy(update={"result_run_id": run_id_for_attempt(attempt)})

    try:
        job = runner.start(
            "render",
            argv,
            meta={"shown": shown, "run_id": run_id, "progress_file": str(progress_file)},
            on_finish=found_film,
            job_id=job_id,
        )
    except JobBusy as busy:
        return _busy(busy, config)
    return _view(config, job)


@router.post("/roster/scan", response_model=JobView, status_code=202, responses={409: {}})
def scan_people(
    config: Annotated[Config, Depends(current_config)],
    runner: Annotated[JobRunner, Depends(job_runner)],
    executable: Annotated[str, Depends(cli_executable)],
) -> JobView | JSONResponse:
    """Read the library's people again with `people scan`, keeping every answer given."""
    config_flag = _config_flag()
    argv = [executable, *(["--config", str(config_flag)] if config_flag else []), "people", "scan"]
    try:
        job = runner.start("scan", argv, meta={"shown": "immich-memories people scan"})
    except JobBusy as busy:
        return _busy(busy, config)
    return _view(config, job)


@router.get("/jobs/active", response_model=JobView | None)
def active_job(
    config: Annotated[Config, Depends(current_config)],
    runner: Annotated[JobRunner, Depends(job_runner)],
) -> JobView | None:
    """The job running now, for a page that opens mid-cut to join it."""
    job = runner.active()
    return _view(config, job) if job else None


def _job(runner: JobRunner, job_id: str) -> Job:
    job = runner.get(job_id)
    if job is None:
        raise HTTPException(404, "No such job.")
    return job


@router.get("/jobs/{job_id}", response_model=JobView)
def read_job(
    job_id: str,
    config: Annotated[Config, Depends(current_config)],
    runner: Annotated[JobRunner, Depends(job_runner)],
) -> JobView:
    """Where the job is, from its record and the files its child writes."""
    return _view(config, _job(runner, job_id))


@router.get("/jobs/{job_id}/events")
async def job_events(
    job_id: str,
    config: Annotated[Config, Depends(current_config)],
    runner: Annotated[JobRunner, Depends(job_runner)],
) -> StreamingResponse:
    """Server-sent events: the job's view on every change, until it finishes."""
    _job(runner, job_id)

    async def stream() -> AsyncIterator[str]:
        previous = ""
        while True:
            view = _view(config, _job(runner, job_id)).model_dump_json()
            if view != previous:
                previous = view
                yield f"data: {view}\n\n"
            if json.loads(view)["status"] != "running":
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"cache-control": "no-cache"}
    )


@router.post("/jobs/{job_id}/cancel", response_model=JobView)
def cancel_job(
    job_id: str,
    config: Annotated[Config, Depends(current_config)],
    runner: Annotated[JobRunner, Depends(job_runner)],
) -> JobView:
    """Stop the job's child, from this tab or any other."""
    return _view(config, runner.cancel(job_id) or _job(runner, job_id))


@router.get("/jobs/{job_id}/output", response_class=JSONResponse)
def job_output(job_id: str, runner: Annotated[JobRunner, Depends(job_runner)]) -> JSONResponse:
    """What the child printed, secrets removed: the reason a failed job gives."""
    _job(runner, job_id)
    return JSONResponse({"output": runner.output(job_id)})


@router.get("/runs/{run_id}/film", response_class=FileResponse)
def film(run_id: str, config: Annotated[Config, Depends(current_config)]) -> FileResponse:
    """The rendered film, by byte range so the player can seek."""
    record = RunDatabase(open_store(config)).get_run(run_id)
    if record is None or not record.output_path or not Path(record.output_path).is_file():
        raise HTTPException(404, "This run has no film on disk.")
    return FileResponse(record.output_path, media_type="video/mp4")


_AUDIO = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav"}


def _music_dir(config: Config) -> Path:
    return config.cache.cache_path / "web-music"


def music_file(config: Config, music_id: str) -> Path | None:
    """The track a music id names, only ever inside the web client's music folder."""
    folder = _music_dir(config).resolve()
    for candidate in folder.glob(f"{music_id}*") if folder.is_dir() else ():
        path = candidate.resolve()
        if path.is_file() and path.parent == folder and path.suffix in _AUDIO:
            return path
    return None


@router.post(
    "/runs/{run_id}/music-preview", response_model=JobView, status_code=202, responses={409: {}}
)
def start_music_preview(
    run_id: str,
    config: Annotated[Config, Depends(current_config)],
    runner: Annotated[JobRunner, Depends(job_runner)],
    executable: Annotated[str, Depends(cli_executable)],
) -> JobView | JSONResponse:
    """Generate the music this cut would get with `music preview`, to hear before rendering."""
    from uuid import uuid4

    job_id = uuid4().hex
    out = config.cache.cache_path / "web-jobs" / f"{job_id}-music"
    progress_file = runner.progress_path(job_id)
    config_flag = _config_flag()
    argv = [
        executable,
        *(["--config", str(config_flag)] if config_flag else []),
        "music",
        "preview",
        run_id,
        "--out",
        str(out),
        "--progress-file",
        str(progress_file),
    ]

    def kept_track(job: Job) -> Job:
        record = json.loads(progress_file.read_text()) if progress_file.is_file() else {}
        made = Path(str(record.get("output_path") or ""))
        if made.is_file() and made.suffix in _AUDIO:
            _music_dir(config).mkdir(parents=True, exist_ok=True)
            shutil.copyfile(made, _music_dir(config) / f"preview-{job.id}{made.suffix}")
            job.meta["music_id"] = f"preview-{job.id}"
        return job

    try:
        job = runner.start(
            "music",
            argv,
            meta={
                "shown": f"immich-memories music preview {run_id}",
                "run_id": run_id,
                "progress_file": str(progress_file),
            },
            on_finish=kept_track,
            job_id=job_id,
        )
    except JobBusy as busy:
        return _busy(busy, config)
    return _view(config, job)


class MusicTrack(BaseModel):
    id: str
    name: str


# A soundtrack is minutes of compressed audio; 64 MiB is generous for MP3/M4A and still bounds
# what one upload can put on disk (S10).
MAX_MUSIC_UPLOAD_BYTES = 64 * 1024 * 1024
_AUDIO_MAGIC = (b"ID3", b"RIFF", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")


def _sounds_like_audio(payload: bytes) -> bool:
    # M4A is an MP4 container: its 'ftyp' box sits at offset 4.
    return payload.startswith(_AUDIO_MAGIC) or payload[4:8] == b"ftyp"


@router.post("/music", response_model=MusicTrack, status_code=201)
async def upload_music(
    file: UploadFile, config: Annotated[Config, Depends(current_config)]
) -> MusicTrack:
    """Keep an uploaded MP3, M4A or WAV for renders to use."""
    from uuid import uuid4

    suffix = Path(file.filename or "").suffix.lower()
    payload = await file.read(MAX_MUSIC_UPLOAD_BYTES + 1)
    if len(payload) > MAX_MUSIC_UPLOAD_BYTES:
        raise HTTPException(413, "That file is too large for a soundtrack")
    # Suffix AND content: the browser's accept= filter is advisory, and a renamed executable
    # must not reach FFmpeg (S10).
    if suffix not in _AUDIO or not _sounds_like_audio(payload):
        raise HTTPException(422, "That file is not an MP3, M4A or WAV")
    music_id = f"upload-{uuid4().hex}"
    _music_dir(config).mkdir(parents=True, exist_ok=True)
    (_music_dir(config) / f"{music_id}{suffix}").write_bytes(payload)
    return MusicTrack(id=music_id, name=file.filename or music_id)


@router.get("/music/{music_id}", response_class=FileResponse)
def music(music_id: str, config: Annotated[Config, Depends(current_config)]) -> FileResponse:
    """A previewed or uploaded track, for the player."""
    path = music_file(config, music_id)
    if path is None:
        raise HTTPException(404, "No such track.")
    return FileResponse(path, media_type=_AUDIO[path.suffix])
