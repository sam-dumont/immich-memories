"""Configuration for what the source model admits and how long a clip is expected to run.

The knobs the legacy clip scorer read (scene detection, segment lengths, audio
boundaries, subject quotas) went with it; `config_loader` refuses a file that
still names one.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from immich_memories.processing.live_material import MIN_LIVE_MOTION_SECONDS


class SpeechConfig(BaseModel):
    """Local voice activity detection before editorial intervals are fixed."""

    enabled: bool = Field(default=True, description="Move video cuts out of detected speech")
    vad_threshold: float = Field(default=0.25, ge=0.1, le=0.9)
    min_silence_ms: int = Field(default=200, ge=50, le=2000)


class AnalysisConfig(BaseModel):
    """Settings for source discovery and admission."""

    download_workers: int = Field(
        default=3,
        ge=1,
        le=8,
        description="Concurrent isolated clients used for video and thumbnail prefetching",
    )
    source_prepare_workers: Annotated[int, Field(ge=1, le=4)] | Literal["auto"] = Field(
        default="auto",
        description="Concurrent selected-source download and preparation workers. "
        "'auto' keeps 1 GB for the app, then prepares one source per 3 GB left of what "
        "this process may use (the container's memory limit, else the machine's RAM), "
        "at least 1 and at most 2",
    )
    prepared_source_cache_max_size_gb: float = Field(
        default=10.0,
        ge=0,
        le=500,
        description="Disk kept for sources earlier runs prepared (cut segments, photo "
        "clips, Live Photo merges), so rendering the same selection again prepares "
        "nothing it already holds. Least recently used go first; 0 keeps none",
    )
    max_album_assets: int = Field(
        default=10000,
        ge=1,
        description="Per media type, the most assets read from an album. "
        "Smart albums reach tens of thousands; Immich returns newest first, so a "
        "larger album is truncated to its most recent assets.",
    )
    # The messaging-app globs carry their prefix and four-digit counter on
    # purpose: "*-wa[0-9]*" alone also matches a photograph of Olympia-WA2019.
    exclude_filename_patterns: list[str] = Field(
        default_factory=lambda: [
            "RingVideo_*",
            "RPReplay_Final*",
            "Screen Recording *",
            "Screenshot*",
            "img-*-wa[0-9][0-9][0-9][0-9]*",
            "vid-*-wa[0-9][0-9][0-9][0-9]*",
        ],
        description="Case-insensitive globs for source files a memory must "
        "never use. Settles for free, before the editor pays for the source, what "
        "a model would otherwise need to decide.",
    )
    exclude_stills_without_camera_exif: bool = Field(
        default=True,
        description="Drop photographs whose EXIF names no camera — on a real "
        "library 1532 of 1541 such stills were received or downloaded. Turn "
        "off for a library of exported originals. Videos are exempt.",
    )
    forwarded_copies_when_short: bool = Field(
        default=False,
        description="Let forwarded copies and saved images (no camera behind them) fill gaps in "
        "the film's camera timeline: an occurrence, week, month or year with no camera picture, "
        "about as many days as a stretch with camera pictures gets. Only when they pass every "
        "check a camera picture does; collages and copies of a picture the library holds stay "
        "out. A copy is dated when it was received, so a re-shared old photo can land in the "
        "wrong year",
    )
    optimal_clip_duration: float = Field(
        default=5.0,
        ge=2.0,
        le=15.0,
        description="Expected seconds per clip when a trip or album sizes its own duration",
    )

    # Live Photo settings
    include_live_photos: bool = Field(
        default=True,
        description="Include Live Photo video clips; one plays as motion when its clip lasts at least 2.5 s and moves",
    )
    live_photo_merge_window_seconds: float = Field(
        default=10.0,
        ge=1.0,
        le=60.0,
        description="Max gap between Live Photos to group into a burst cluster",
    )
    # The motion floor for every Live clip, stitched or single (#2453). It was 3.5 s and
    # applied to joins only; see `MIN_LIVE_MOTION_SECONDS`.
    live_photo_min_clip_seconds: float = Field(
        default=MIN_LIVE_MOTION_SECONDS,
        ge=0.0,
        le=30.0,
        description=(
            "The shortest clip a Live Photo plays as motion, a stitch of nearby Live Photos "
            "or its own; anything shorter plays as its still"
        ),
    )

    min_source_short_side: int = Field(
        default=1080,
        ge=0,
        description=(
            "Unknown clips below this short side are dropped; it also enables the "
            "measured 2048px UUID-JPEG forwarded-media fingerprint. Camera EXIF, a "
            "favorite, and media captured before 2008 override the inference"
        ),
    )
    max_source_video_seconds: float = Field(
        default=300.0,
        ge=0,
        description=(
            "Source videos longer than this are excluded from every memory on "
            "Immich's duration metadata, before analysis or download: selecting "
            "six seconds from an hour-long recording once meant downloading all "
            "37GB of it. Missing or unreadable duration metadata excludes the "
            "video too; photographs and Live Photo motion are exempt. 0 disables"
        ),
    )
