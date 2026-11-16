"""Progress headings as a stage key plus params, worded where they are read.

A run says where it is as a key ("render.title") and the values its sentence needs
({"frame": 3, "frames": 90}), never as an English sentence. The web client words the key
from the interface catalogue in the reader's language (`STAGES` in web/src/lib/labels.ts,
the same templates as `STAGE_TEXTS` here); the terminal, and every record a script or an
older reader reads as text, words it here in English from the same `ui.po` templates.

Where a heading still travels as one string (the render callback, the render worker's
status, a progress file), it is carried coded: `stage.<key>?name=value&...`, the shape
operational warnings have (`operational_warnings`). Text that is not coded, such as a line an
earlier version wrote, words as it is.

Params are values the code itself knows (counts, a clip's file name, a provider's name),
never anything read from the config: no URL, key, host or path. A wait travels twice, as
`duration_seconds` for the page to write in its language and as `duration` in English.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum
from urllib.parse import parse_qsl, quote, urlencode

from immich_memories.i18n import DEFAULT_LOCALE, get_translator

_CODED = re.compile(r"^stage\.([a-z0-9_.]+)(?:\?(.*))?$", re.DOTALL)
# A preparation pass reports under its engine name, a scope and a stage: "videos.detectors".
_PASS = re.compile(r"[a-z_]+(?:\.[a-z_]+)?")

Params = Mapping[str, str | int]


class Stage(StrEnum):
    """Every stage the run announces by key, outside the preparation passes."""

    # The cut: editing the pictures into a memory.
    CUT_EVIDENCE = "cut.evidence"
    CUT_METADATA = "cut.metadata"
    CUT_EVENT_EVIDENCE = "cut.event_evidence"
    CUT_EVENT_PACKS = "cut.event_packs"
    CUT_CARDS = "cut.cards"
    CUT_EDITING = "cut.editing"
    CUT_COUNT_FAMILY_CHECK = "cut.count_family_check"
    CUT_COUNT_DUPLICATES = "cut.count_duplicates"
    CUT_COUNT_PICTURE_REVIEW = "cut.count_picture_review"
    CUT_FAMILY_CHECK = "cut.family_check"
    CUT_PERIOD_ACCOUNT = "cut.period_account"
    CUT_TIMING = "cut.timing"
    CUT_COMPLETE = "cut.complete"
    CUT_CANCELLED = "cut.cancelled"
    CUT_FAILED = "cut.failed"
    CUT_BATCH_WAITING = "cut.batch_waiting"
    CUT_READER_WAITING = "cut.reader_waiting"
    CUT_READER_GAVE_UP = "cut.reader_gave_up"
    # A free-text request preparing its period before the cut.
    ASK_UNPREPARED = "ask.unprepared"
    ASK_PREPARED = "ask.prepared"
    # What a job shows before its command has said anything.
    JOB_POOL = "job.pool"
    JOB_RENDER = "job.render"
    JOB_MODELS = "job.models"
    JOB_MODEL = "job.model"
    JOB_DETECTORS = "job.detectors"
    JOB_SENTENCE = "job.sentence"
    JOB_LIBRARY = "job.library"
    # The render.
    RENDER_PREPARING_CLIPS = "render.preparing_clips"
    RENDER_CLIPS_PREPARED = "render.clips_prepared"
    RENDER_DOWNLOADING = "render.downloading"
    RENDER_EXTRACTING = "render.extracting"
    RENDER_SOURCES_PREPARED = "render.sources_prepared"
    RENDER_TITLE = "render.title"
    RENDER_TRIP_MAP = "render.trip_map"
    RENDER_TITLE_READY = "render.title_ready"
    RENDER_YEAR_CARD = "render.year_card"
    RENDER_MONTH_CARD = "render.month_card"
    RENDER_LOCATION_CARD = "render.location_card"
    RENDER_ENDING = "render.ending"
    RENDER_ENCODING = "render.encoding"
    RENDER_ENCODING_CLOCK = "render.encoding_clock"
    RENDER_ENCODING_TIME = "render.encoding_time"
    RENDER_ENCODING_SPEED = "render.encoding_speed"
    RENDER_ASSEMBLY = "render.assembly"
    RENDER_AUDIO_MIX = "render.audio_mix"
    RENDER_MUX = "render.mux"
    RENDER_CHECK = "render.check"
    RENDER_CHECK_DECODED = "render.check_decoded"
    RENDER_MUSIC_MUTE = "render.music_mute"
    RENDER_MUSIC = "render.music"
    RENDER_MUSIC_MIX = "render.music_mix"
    RENDER_MUSIC_READY = "render.music_ready"
    RENDER_MUSIC_WARNING = "render.music_warning"
    RENDER_UPLOAD = "render.upload"
    RENDER_UPLOAD_INCOMPLETE = "render.upload_incomplete"
    RENDER_COMPLETE = "render.complete"
    RENDER_WORKER_CHECK = "render.worker_check"
    RENDER_WORKER_QUEUE = "render.worker_queue"
    RENDER_WORKER_DOWNLOAD = "render.worker_download"
    RENDER_WORKER_BYTES = "render.worker_bytes"
    RENDER_WORKER_BYTES_OPEN = "render.worker_bytes_open"
    RENDER_WORKER_FILM_CHECK = "render.worker_film_check"
    # The music, in a film or a preview.
    MUSIC_READING_CUT = "music.reading_cut"
    MUSIC_CHECKING_SERVICE = "music.checking_service"
    MUSIC_GENERATING = "music.generating"
    MUSIC_NEXT_SERVICE = "music.next_service"
    MUSIC_STEMS = "music.stems"


# The English templates, which are the `ui.po` msgids; labels.ts keeps the same table.
_KEYED_TEXTS: dict[str, str] = {
    Stage.CUT_EVIDENCE: "Preparing editorial evidence",
    Stage.CUT_METADATA: "Reading dates, places and people",
    Stage.CUT_EVENT_EVIDENCE: "Reading event evidence",
    Stage.CUT_EVENT_PACKS: "Reading event evidence",
    Stage.CUT_CARDS: "Building editorial cards",
    Stage.CUT_EDITING: "Editing the memory",
    Stage.CUT_COUNT_FAMILY_CHECK: (
        "Editing the memory: {pictures} pictures going into the family-viewing check"
    ),
    Stage.CUT_COUNT_DUPLICATES: "Editing the memory: {pictures} pictures after the duplicate review",
    Stage.CUT_COUNT_PICTURE_REVIEW: (
        "Editing the memory: {pictures} pictures going into the picture review"
    ),
    Stage.CUT_FAMILY_CHECK: "Running the family-viewing check",
    Stage.CUT_PERIOD_ACCOUNT: "Reading the period account: {month}",
    Stage.CUT_TIMING: "Validating selected source timing",
    Stage.CUT_COMPLETE: "Editorial selection complete",
    Stage.CUT_CANCELLED: "Editorial selection cancelled",
    Stage.CUT_FAILED: "Editorial selection failed",
    Stage.CUT_BATCH_WAITING: ("Waiting on the {provider} batch: {count} prompts, submitted {time}"),
    Stage.CUT_READER_WAITING: (
        "Waiting for the reader: connection dropped, retry {attempt} of {retries}"
    ),
    Stage.CUT_READER_GAVE_UP: (
        "Gave up on the reader after {retries} dropped connections: check that server"
    ),
    Stage.ASK_UNPREPARED: (
        "{count} pictures in this period aren't prepared yet; "
        "preparing them first takes about {duration}"
    ),
    Stage.ASK_PREPARED: "{count} pictures prepared",
    Stage.JOB_POOL: "Preparing the pool",
    Stage.JOB_RENDER: "Preparing the render",
    Stage.JOB_MODELS: "Downloading pinned models",
    Stage.JOB_MODEL: "Downloading {name}",
    Stage.JOB_DETECTORS: "Downloading the detector snapshots",
    Stage.JOB_SENTENCE: "Reading your sentence",
    Stage.JOB_LIBRARY: "Reading the library",
    Stage.RENDER_PREPARING_CLIPS: "Preparing clips...",
    Stage.RENDER_CLIPS_PREPARED: "Clips prepared",
    Stage.RENDER_DOWNLOADING: "Downloading: {name}",
    Stage.RENDER_EXTRACTING: "Extracting segment: {name}",
    Stage.RENDER_SOURCES_PREPARED: "Prepared {done}/{total} sources",
    Stage.RENDER_TITLE: "Generating title screen...",
    Stage.RENDER_TRIP_MAP: "Generating trip map...",
    Stage.RENDER_TITLE_READY: "Title screen ready",
    Stage.RENDER_YEAR_CARD: "Year divider {index} of {count}",
    Stage.RENDER_MONTH_CARD: "Month divider {index} of {count}",
    Stage.RENDER_LOCATION_CARD: "Location card {index} of {count}",
    Stage.RENDER_ENDING: "Generating ending screen...",
    Stage.RENDER_ENCODING: "Encoding video...",
    Stage.RENDER_ENCODING_CLOCK: "Encoding ({done} / {total}) — {percent}%",
    Stage.RENDER_ENCODING_TIME: "Encoding ({time})",
    Stage.RENDER_ENCODING_SPEED: "Encoding ({time}) @ {speed}x",
    Stage.RENDER_ASSEMBLY: "Streaming video assembly...",
    Stage.RENDER_AUDIO_MIX: "Mixing audio...",
    Stage.RENDER_MUX: "Muxing final output...",
    Stage.RENDER_CHECK: "Checking the finished film",
    Stage.RENDER_CHECK_DECODED: "Checking the finished film: {done} of {total} decoded",
    Stage.RENDER_MUSIC_MUTE: "Muting original audio...",
    Stage.RENDER_MUSIC: "Generating music...",
    Stage.RENDER_MUSIC_MIX: "Mixing music...",
    Stage.RENDER_MUSIC_READY: "Music ready",
    Stage.RENDER_MUSIC_WARNING: "Music finished with a warning",
    Stage.RENDER_UPLOAD: "Uploading to Immich...",
    Stage.RENDER_UPLOAD_INCOMPLETE: "Immich delivery incomplete; local film kept",
    Stage.RENDER_COMPLETE: "Complete!",
    Stage.RENDER_WORKER_CHECK: "Checking the render worker",
    Stage.RENDER_WORKER_QUEUE: "Waiting for the render worker",
    Stage.RENDER_WORKER_DOWNLOAD: "Downloading the finished film",
    Stage.RENDER_WORKER_BYTES: "Downloading the finished film: {done}/{total} bytes",
    Stage.RENDER_WORKER_BYTES_OPEN: "Downloading the finished film: {done} bytes received",
    Stage.RENDER_WORKER_FILM_CHECK: "Checking the downloaded film",
    Stage.MUSIC_READING_CUT: "Reading the cut for music",
    Stage.MUSIC_CHECKING_SERVICE: "Checking music service",
    Stage.MUSIC_GENERATING: "Generating music",
    Stage.MUSIC_NEXT_SERVICE: "Music service failed; trying the next service",
    Stage.MUSIC_STEMS: "Separating stems",
}

# The preparation passes, under the engine names they report with.
PASS_TEXTS: dict[str, str] = {
    "reused": "Reusing saved picture checks",
    "skipped_models": "Model checks not requested",
    "skipped_captions": "Descriptions not requested",
    "previews": "Fetching picture previews",
    "pixels": "Measuring the pictures",
    "faces": "Finding faces",
    "public_heads": "Reading what each picture shows",
    "detectors": "Checking pictures for the family audience",
    "motion": "Measuring motion in the videos",
    "captions": "Describing the pictures",
    "remote_facts": "Reading picture facts",
    "obstruction": "Checking for a covered lens",
    "videos.previews": "Fetching video clip previews",
    "videos.detectors": "Checking video frames for the family audience",
    "videos.detector_frames": "Sampling video frames",
    "videos.remote_frames": "Checking video clips",
    "videos.clip_frames": "Reading what each video shows",
    "videos.video_motion": "Measuring motion in video clips",
    "videos.obstruction_frames": "Checking video clips for a covered lens",
    "live_photos.previews": "Fetching Live Photo clip previews",
    "live_photos.detectors": "Checking Live Photo frames for the family audience",
    "live_photos.detector_frames": "Sampling Live Photo frames",
    "live_photos.remote_frames": "Checking Live Photo clips",
    "live_photos.clip_frames": "Reading what each Live Photo clip shows",
    "live_photos.video_motion": "Measuring motion in Live Photo clips",
    "live_photos.obstruction_frames": "Checking Live Photo clips for a covered lens",
    # A pass this table does not name yet still reads as what its scope is doing.
    "videos.other": "Checking video clips",
    "live_photos.other": "Checking Live Photo clips",
    "pictures.other": "Preparing the pictures",
}

STAGE_TEXTS: dict[str, str] = _KEYED_TEXTS | PASS_TEXTS

# A card that counts its rendered frames says so after its own heading.
FRAMED = "{stage} (frame {frame}/{frames})"

# The names ETA history kept stages under before they had keys, so a finished run's
# measurements still estimate the next one.
_LEGACY_SPAN_KEYS = {
    "Preparing editorial evidence": Stage.CUT_EVIDENCE,
    "Reading dates, places and people": Stage.CUT_METADATA,
    "Reading event evidence": Stage.CUT_EVENT_EVIDENCE,
    "event evidence": Stage.CUT_EVENT_PACKS,
    "Building editorial cards": Stage.CUT_CARDS,
    "Editing the memory": Stage.CUT_EDITING,
    "the family-viewing check": Stage.CUT_FAMILY_CHECK,
    "Reading the period account": Stage.CUT_PERIOD_ACCOUNT,
    "Validating selected source timing": Stage.CUT_TIMING,
    "Waiting for the reader": Stage.CUT_READER_WAITING,
    "Gave up on the reader": Stage.CUT_READER_GAVE_UP,
}
_LEGACY_BATCH = re.compile(r"^waiting on .+ batch$")


def coded(stage: Stage, **params: str | int) -> str:
    """The one-string form of a heading: `stage.<key>` and its params, percent-encoded."""
    return _coded(stage.value, params)


def coded_pass(name: str, **params: str | int) -> str:
    """A preparation pass's heading, under the key its engine name words as."""
    return _coded(catalogue_key(name) or "pictures.other", params)


def _coded(key: str, params: Params) -> str:
    query = urlencode({k: str(v) for k, v in params.items()}, quote_via=quote)
    return f"stage.{key}?{query}" if query else f"stage.{key}"


def parse(text: str) -> tuple[str, dict[str, str]] | None:
    """A coded heading's key and params; None for any other text."""
    match = _CODED.match(text)
    if match is None or match.group(1) not in STAGE_TEXTS:
        return None
    return match.group(1), dict(parse_qsl(match.group(2) or "", keep_blank_values=True))


def as_stage(text: str, fallback: Stage) -> str:
    """`text` when it is a coded heading, else `fallback`: a backend's own status words
    nothing a reader can translate, so its stage says what kind of work it is."""
    return text if parse(text) is not None else coded(fallback)


def catalogue_key(label: str) -> str:
    """The catalogue key a stage label words under, or "" for an English line from before keys.

    A preparation pass the table does not list yet words as its scope's generic pass, so
    every label the backend emits has a heading in every language.
    """
    if label in STAGE_TEXTS:
        return label
    if not _PASS.fullmatch(label):
        return ""
    scope = label.split(".", 1)[0] if "." in label else ""
    return f"{scope}.other" if f"{scope}.other" in STAGE_TEXTS else "pictures.other"


def heading(text: str) -> tuple[str, dict[str, str]]:
    """The key and params a one-string heading carries; ("", {}) for uncoded text."""
    return parse(text) or ("", {})


def words(key: str, params: Params | None = None, locale: str = DEFAULT_LOCALE) -> str:
    """The heading for `key` in `locale`, its params filled in, as the web client words it."""
    template = STAGE_TEXTS.get(key)
    if template is None:
        return key
    translate = get_translator(locale, "ui").gettext
    values = {name: str(value) for name, value in (params or {}).items()}
    text = translate(template).format_map(_Kept(values))
    if "frame" in values and "frames" in values:
        text = translate(FRAMED).format(stage=text, frame=values["frame"], frames=values["frames"])
    return text


def stage_text(text: str, locale: str = DEFAULT_LOCALE) -> str:
    """A one-string heading worded in `locale`; text that is not coded is unchanged."""
    parsed = parse(text)
    return text if parsed is None else words(parsed[0], parsed[1], locale)


def current_span_name(name: str) -> str:
    """A stage span's name as this version keys it; history from before keys is renamed."""
    prefix, _, rest = name.partition(".")
    phase, _, stage = rest.partition(".")
    if prefix != "stage" or not stage:
        return name
    key = _LEGACY_SPAN_KEYS.get(stage)
    if key is None and _LEGACY_BATCH.match(stage):
        key = Stage.CUT_BATCH_WAITING
    return f"stage.{phase}.{key.value}" if key is not None else name


class _Kept(dict):
    """Leave a placeholder the params do not fill as it is, rather than fail the heading."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"
