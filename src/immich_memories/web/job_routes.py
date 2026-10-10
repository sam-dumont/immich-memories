"""Start a cut or a render from the browser, follow it, cancel it, and play the film it made."""

from __future__ import annotations

import asyncio
import json
import math
import re
import shlex
import shutil
import subprocess  # noqa: S404 - bounded local audio probe, no shell
import sys
import tempfile
from collections.abc import AsyncIterator
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from immich_memories.config import get_config_path
from immich_memories.config_loader import Config
from immich_memories.config_models_render import TitleStyleMode
from immich_memories.db import open_store
from immich_memories.operations.cut_progress import (
    StageUpdate,
    live_progress_of,
    read_latest_attempt,
    recent_pictures_of,
)
from immich_memories.operations.run_index import attempt_dir_for_run, run_id_for_attempt
from immich_memories.tracking import RunDatabase
from immich_memories.tracking.phase_forecast import forecast_at
from immich_memories.web.brief import CutBrief
from immich_memories.web.dependencies import current_config
from immich_memories.web.film_downloads import (
    FinishedFilmFetcher,
    finished_film,
    immich_finished_film,
)
from immich_memories.web.film_files import FILM_TYPES, local_film
from immich_memories.web.jobs import JobBusy, JobRunner
from immich_memories.web.schemas import AskPreview, Job, JobProgress

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
    fade_color: Literal["white", "black"] | None = None
    title_style: TitleStyleMode | None = None
    # "none", "auto" (as configured), or the id of a previewed or uploaded track.
    music: str = "auto"
    music_volume: float | None = None
    original_audio: bool | None = None
    # None follows defaults.add_date / add_place, as `runs render` does with neither flag.
    add_date: bool | None = None
    add_place: bool | None = None
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
            "fade_color",
            "title_style",
            "music_volume",
            "album",
        )
        switches = ("privacy_mode", "upload_to_immich")
        either_way = ("add_date", "add_place", "original_audio")
        return [
            *(
                f"--{n.replace('_', '-')}={getattr(self, n)}"
                for n in valued
                if getattr(self, n) is not None
            ),
            *(f"--{n.replace('_', '-')}" for n in switches if getattr(self, n)),
            *(
                f"--{'' if getattr(self, n) else 'no-'}{n.replace('_', '-')}"
                for n in either_way
                if getattr(self, n) is not None
            ),
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


def _progress_file_record(job: Job) -> dict[str, Any]:
    path = Path(str(job.meta.get("progress_file") or ""))
    try:
        record = json.loads(path.read_text()) if path.is_file() else {}
        return record if isinstance(record, dict) else {}
    except (ValueError, OSError):
        return {}


def _preparing_progress(job: Job) -> JobProgress | None:
    """An unprepared window's warning, read before any attempt -- and so any stage -- exists."""
    record = _progress_file_record(job)
    message = record.get("message")
    if not message:
        return None
    return JobProgress(
        label=str(message),
        phase=str(record.get("phase") or ""),
        fraction=record.get("fraction"),
        remaining_seconds=record.get("remaining_seconds"),
        fraction_scope=record.get("fraction_scope", "unknown"),
        stage_fraction=record.get("stage_fraction"),
        stage_name=str(record.get("stage_name") or ""),
        scope=str(record.get("scope") or ""),
        pass_id=record.get("pass_id", 0),
        updated_at=record.get("updated_at"),
        last_completed_at=record.get("last_completed_at"),
    )


def _cut_progress(config: Config, job: Job) -> JobProgress:
    record = read_latest_attempt(_cut_root(config, job.id))
    if record is None:
        return _preparing_progress(job) or JobProgress(label="Preparing the pool")
    live = live_progress_of(record) or StageUpdate.from_record(record.get("progress"))
    if live is None:
        return JobProgress(
            label=str(record.get("stage") or ""),
            stage_name=str((record.get("progress") or {}).get("label") or ""),
            recent_asset_ids=list(recent_pictures_of(record)),
        )
    forecast = forecast_at(live.forecast)
    return JobProgress(
        label=str(record.get("stage") or ""),
        stage_name=live.label,
        history=record.get("stage_history", []),
        forecast=forecast,
        fraction_scope="stage" if live.fraction is not None else "unknown",
        stage_fraction=live.fraction,
        unit=live.unit,
        scope=live.scope,
        pass_id=live.pass_id,
        updated_at=live.updated_at,
        last_completed_at=live.last_completed_at,
        phase=live.phase,
        done=live.done,
        total=live.total,
        fraction=live.fraction if live.total_fraction is None else live.total_fraction,
        remaining_seconds=forecast["remaining_seconds"]
        if forecast
        else live.total_remaining_seconds,
        stage_remaining_seconds=live.remaining_seconds if live.remaining_label else None,
        recent_asset_ids=list(recent_pictures_of(record)),
    )


def _render_progress(job: Job) -> JobProgress:
    record = _progress_file_record(job)
    forecast = forecast_at(record.get("forecast"))
    return JobProgress(
        label=str(record.get("message") or "Preparing the render"),
        history=record.get("stage_history", []),
        forecast=forecast,
        phase=str(record.get("phase") or ""),
        fraction=record.get("fraction"),
        remaining_seconds=forecast["remaining_seconds"]
        if forecast
        else record.get("remaining_seconds"),
        fraction_scope=record.get("fraction_scope", "unknown"),
        stage_fraction=record.get("stage_fraction"),
        stage_name=str(record.get("stage_name") or ""),
        scope=str(record.get("scope") or ""),
        pass_id=record.get("pass_id", 0),
        updated_at=record.get("updated_at"),
        last_completed_at=record.get("last_completed_at"),
    )


def _view(config: Config, job: Job) -> JobView:
    if job.kind == "cut":
        progress = _cut_progress(config, job)
    elif job.kind in {"render", "music"}:
        progress = _render_progress(job)
    elif job.kind == "models":
        matches = re.findall(
            r"^models: (\d+)/(\d+) (.+)$",
            _runner(config.cache.cache_path).output(job.id),
            re.MULTILINE,
        )
        if matches:
            index, total, label = matches[-1]
            done = int(index) - 1
            progress = JobProgress(
                label=label,
                done=done,
                total=int(total),
                fraction=done / int(total),
                fraction_scope="stage",
                stage_fraction=done / int(total),
            )
        else:
            progress = JobProgress(label="Downloading pinned models")
    elif job.kind == "ask":
        progress = JobProgress(label="Reading your sentence")
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
    # `--ask`'s own progress file: a sibling of --output, so an unprepared window's warning
    # (count, estimate) reaches the page before any attempt -- and therefore any stage -- exists.
    progress_file = output.with_suffix(".preparing.json")

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
            meta={
                "shown": brief.shown_command(),
                "brief": brief.model_dump_json(),
                "progress_file": str(progress_file),
            },
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


_NEEDS_MODEL_TIER = (
    "A film from a sentence needs the model tier: set advanced.llm.base_url and "
    "advanced.llm.model to the reader that answers it (tier: full)"
)


class AskAvailability(BaseModel):
    available: bool
    tier: str


@router.get("/ask", response_model=AskAvailability)
def ask_availability(config: Annotated[Config, Depends(current_config)]) -> AskAvailability:
    """Whether a film can be asked for in a sentence: the model tier reads it (`generate --ask`)."""
    return AskAvailability(available=config.tier == "full", tier=config.tier)


class AskRequest(BaseModel):
    sentence: str = Field(min_length=1, max_length=500)
    # The accounts the page has chosen (`CutBrief.accounts`): a preview must scope its pool
    # the same way the film it is previewing will (#2044), or the preview can show pictures
    # the eventual film's own accounts would never have counted.
    accounts: list[str] = Field(default_factory=list)


@router.post("/ask/preview", response_model=JobView, status_code=202, responses={409: {}})
def start_ask_preview(
    request: AskRequest,
    config: Annotated[Config, Depends(current_config)],
    runner: Annotated[JobRunner, Depends(job_runner)],
    executable: Annotated[str, Depends(cli_executable)],
) -> JobView | JSONResponse:
    """Translate a sentence with `generate --ask --dry-run`; nothing is filmed.

    The CLI keeps the translation in a JSON file beside the job, which the preview reads.
    """
    from uuid import uuid4

    if config.tier != "full":
        raise HTTPException(422, _NEEDS_MODEL_TIER)
    sentence = request.sentence.strip()
    if not sentence:
        raise HTTPException(422, "Describe the film you want.")
    job_id = uuid4().hex
    trace_file = runner.progress_path(job_id)
    config_flag = _config_flag()
    # The same `CutBrief` flags a film from this sentence would get (`accounts` included),
    # so the preview's pool is scoped exactly as the eventual render will be.
    flags = [*CutBrief(ask=sentence, accounts=request.accounts).flags(), "--dry-run"]
    argv = [
        executable,
        *(["--config", str(config_flag)] if config_flag else []),
        "generate",
        *flags,
        "--ask-trace",
        str(trace_file),
    ]
    shown = shlex.join(["immich-memories", "generate", *flags])
    try:
        job = runner.start(
            "ask", argv, meta={"shown": shown, "trace_file": str(trace_file)}, job_id=job_id
        )
    except JobBusy as busy:
        return _busy(busy, config)
    return _view(config, job)


@router.get("/ask/preview/{job_id}", response_model=AskPreview)
def ask_preview(job_id: str, runner: Annotated[JobRunner, Depends(job_runner)]) -> AskPreview:
    """The translation a finished preview kept; 404 until it has one."""
    job = _job(runner, job_id)
    path = Path(str(job.meta.get("trace_file") or ""))
    if job.kind != "ask" or not path.is_file():
        raise HTTPException(404, "This preview kept no translation.")
    return AskPreview.model_validate_json(path.read_text())


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
    try:
        job = runner.get(job_id)
    except ValueError as error:
        raise HTTPException(404, "No such job.") from error
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
    job = _job(runner, job_id)
    return _view(config, runner.cancel(job_id) or job)


@router.get("/jobs/{job_id}/output", response_class=JSONResponse)
def job_output(job_id: str, runner: Annotated[JobRunner, Depends(job_runner)]) -> JSONResponse:
    """What the child printed, secrets removed: the reason a failed job gives."""
    _job(runner, job_id)
    return JSONResponse({"output": runner.output(job_id)})


@router.get("/runs/{run_id}/film", response_class=FileResponse)
def film(run_id: str, config: Annotated[Config, Depends(current_config)]) -> FileResponse:
    """The rendered film, by byte range so the player can seek.

    A run's page checks `film_available` before ever requesting this, so
    reaching here for a delivered run means a stale link, not a broken
    player: the local copy was reclaimed once Immich confirmed the upload.
    """
    record = RunDatabase(open_store(config)).get_run(run_id)
    if record is None or not record.output_path:
        raise HTTPException(404, "This run has no film on disk.")
    path = local_film(record)
    if path is None:
        if record.delivery_status.value == "delivered":
            raise HTTPException(
                404, "The local film was removed after delivery; it is in Immich now."
            )
        raise HTTPException(404, "This run has no film on disk.")
    return FileResponse(path, media_type=FILM_TYPES[path.suffix.lower()])


@router.get("/runs/{run_id}/download", response_class=FileResponse)
def download_film(
    run_id: str,
    config: Annotated[Config, Depends(current_config)],
    fetch: Annotated[FinishedFilmFetcher, Depends(immich_finished_film)],
) -> FileResponse:
    """Download only this saved run's artifact, locally or from its delivery record."""
    record = RunDatabase(open_store(config)).get_run(run_id)
    if record is None:
        raise HTTPException(404, "Run not found.")
    return finished_film(config, record, fetch)


_AUDIO = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav"}


def _music_dir(config: Config) -> Path:
    return config.cache.cache_path / "web-music"


def music_file(config: Config, music_id: str) -> Path | None:
    """The track a music id names, only ever inside the web client's music folder."""
    if re.fullmatch(r"(?:upload|preview)-[0-9a-f]{32}", music_id) is None:
        return None
    folder = _music_dir(config).resolve()
    for suffix in _AUDIO:
        path = (folder / f"{music_id}{suffix}").resolve()
        if path.is_file() and path.parent == folder:
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
    if attempt_dir_for_run(run_id, store=open_store(config)) is None:
        raise HTTPException(404, "This run left no saved cut.")
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


def _usable_audio(path: Path) -> bool:
    try:
        result = subprocess.run(  # noqa: S603 - fixed probe arguments and a server-owned path
            [
                "ffprobe",
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-probesize",
                "5000000",
                "-analyzeduration",
                "5000000",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_type:format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            check=True,
            timeout=10,
        )
        probe = json.loads(result.stdout)
        duration = float(probe.get("format", {}).get("duration", 0))
        return bool(probe.get("streams")) and math.isfinite(duration) and duration > 0
    except FileNotFoundError as error:
        raise HTTPException(503, "Audio checking is unavailable: install FFmpeg") from error
    except (subprocess.SubprocessError, ValueError):
        return False


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
    folder = _music_dir(config)
    folder.mkdir(parents=True, exist_ok=True)
    kept = folder / f"{music_id}{suffix}"
    with tempfile.TemporaryDirectory(dir=folder) as temporary:
        candidate = Path(temporary) / kept.name
        candidate.write_bytes(payload)
        candidate.chmod(0o600)
        if not await run_in_threadpool(_usable_audio, candidate):
            raise HTTPException(422, "That file has no usable audio stream or duration")
        candidate.replace(kept)
    _evict_oldest_uploads(folder, config.server.music_upload_quota_mb, keep=kept)
    return MusicTrack(id=music_id, name=file.filename or music_id)


def _evict_oldest_uploads(folder: Path, quota_mb: int, *, keep: Path) -> None:
    uploads = sorted(folder.glob("upload-*"), key=lambda path: path.stat().st_mtime_ns)
    total = sum(path.stat().st_size for path in uploads)
    for path in uploads:
        if total <= quota_mb * 1024 * 1024:
            return
        if path != keep:
            total -= path.stat().st_size
            path.unlink(missing_ok=True)


@router.get("/music/{music_id}", response_class=FileResponse)
def music(music_id: str, config: Annotated[Config, Depends(current_config)]) -> FileResponse:
    """A previewed or uploaded track, for the player."""
    path = music_file(config, music_id)
    if path is None:
        raise HTTPException(404, "No such track.")
    return FileResponse(path, media_type=_AUDIO[path.suffix])
