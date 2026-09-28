"""The /api/v1 contract. The TypeScript client is generated from these models."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, field_serializer


class RunSummary(BaseModel):
    run_id: str
    status: str
    source: str
    created_at: datetime
    memory_type: str | None
    date_range_start: date | None
    date_range_end: date | None
    preview_asset_ids: list[str]
    # False for a cut that stopped before rendering: it can be reviewed and rendered.
    film: bool

    @field_serializer("created_at")
    def _rfc3339(self, value: datetime) -> str:
        # Runs record UTC today; an older row without a zone was `datetime.now()`, server-local
        # time, which is how astimezone() reads a naive value.
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class RunPage(BaseModel):
    runs: list[RunSummary]
    next_offset: int | None


class SelectionPath(BaseModel):
    """What the rules decided about a picture, in the words `runs why` prints."""

    facts: str
    passed: list[str]
    left_out_at: str | None
    left_out_because: str | None
    kept_at: str | None


class ModelDecision(BaseModel):
    """What the model polish recorded about a shot; absent when no model read the cut."""

    model_reason: str
    kept_reason: str
    proposed_asset_id: str
    offered_count: int
    replacement_outcome: str
    replaced_asset_id: str
    seat: str


class Alternative(BaseModel):
    """Another picture of the shot's moment, eligible when the shot was chosen."""

    asset_id: str
    facts: str
    fate: str


class CutShot(BaseModel):
    asset_id: str
    position: int
    start: float
    seconds: float
    taken: str
    day: str
    new_day: bool
    chapter: str
    story_key: str
    story_title: str
    moment: str
    reason: str
    motion: bool
    # The seconds the renderer counts for this shot (its recorded interval); `seconds` is the
    # storyboard's display length, squeezed when a cut runs long.
    recorded_seconds: float
    source_interval: tuple[float, float] | None
    selection: SelectionPath | None
    model: ModelDecision | None
    alternatives: list[Alternative]


class Cut(BaseModel):
    run_id: str
    thesis: str
    content_seconds: float
    content_budget_seconds: float | None
    film_seconds: float | None
    model_polish: bool
    shots: list[CutShot]


class StoryCarrier(BaseModel):
    asset_id: str
    seconds: float
    taken: str
    reason: str
    motion: bool


class StoryPart(BaseModel):
    key: str
    title: str
    # The editor's own word: dominant, major, minor, glimpse, or none. The client words it.
    weight: str
    purpose: str
    granted: int
    day: str
    carriers: list[StoryCarrier]


class StoryLength(BaseModel):
    requested_seconds: float
    content_budget_seconds: float
    selected_content_seconds: float
    status: str


class Story(BaseModel):
    thesis: str
    preparation: str
    duration: StoryLength | None
    stories: list[StoryPart]


class PhaseTiming(BaseModel):
    name: str
    seconds: float
    errors: list[str]


class RunDetail(RunSummary):
    completed_at: datetime | None
    output_path: str | None
    delivery_status: str
    warnings: list[str]
    phases: list[PhaseTiming]
    clips_selected: int
    has_cut: bool
    child_output: bool


class RevisionEdits(BaseModel):
    """What the owner changed: removals and swaps name the cut's shots, additions its pool."""

    removed: list[str] = []
    segments: dict[str, tuple[float, float]] = {}
    swaps: dict[str, str] = {}
    added: list[str] = []


class Revision(RevisionEdits):
    number: int
    created_at: str
    content_seconds: float


class Hold(BaseModel):
    """`never_use`, `cleared:<level>` or None; `reasons` say what holds the picture, if anything."""

    decision: str | None
    reasons: list[str]
    can_clear: bool


class PoolItem(BaseModel):
    asset_id: str
    taken: str
    kind: Literal["photo", "video", "live"]
    favourite: bool
    in_cut: bool
    # False when the editor never received it (outside this memory's material): a tick can't reach it.
    reachable: bool
    fate: str
    hold: Hold


class Pool(BaseModel):
    total: int
    # Pictures left out of this listing because the editor never received them.
    outside: int = 0
    items: list[PoolItem]


class Decision(BaseModel):
    action: Literal["never_use", "clear", "forget"]
    level: Literal["anyone", "family", "just-us"] = "anyone"


JobKind = Literal["cut", "render", "scan", "music"]
JobStatus = Literal["running", "succeeded", "failed", "cancelled", "interrupted"]


class Job(BaseModel):
    id: str
    kind: JobKind
    argv: list[str]
    status: JobStatus = "running"
    started_at: float
    finished_at: float | None = None
    exit_code: int | None = None
    pid: int | None = None
    cancel_requested: bool = False
    meta: dict[str, str | int | None] = {}
    result_run_id: str | None = None


class SessionView(BaseModel):
    auth_enabled: bool
    provider: str | None
    signed_in: bool
    username: str | None
    button_text: str | None
    auto_launch: bool
    # `server.enable_demo_mode`: whether the blur switch is on offer at all.
    demo_mode_offered: bool = False
    # A music generator (MusicGen or ACE-Step) is configured, so a track can be previewed.
    music_preview_offered: bool = False


class Language(BaseModel):
    code: str
    name: str


class Messages(BaseModel):
    locale: str
    messages: dict[str, str]
    # Every interface language, each named in its own tongue, for the picker.
    languages: list[Language]


class Connection(BaseModel):
    url: str
    has_key: bool


class ConnectionEntry(BaseModel):
    url: str
    # Empty means "keep the stored key": the field always loads empty.
    api_key: str = ""


class Greeting(BaseModel):
    user: str


class JobProgress(BaseModel):
    label: str = ""
    # The stage's own name ("previews", "public_heads"), for the page to word; `label` is the
    # engine's sentence.
    stage_name: str = ""
    phase: str = ""
    done: int | None = None
    total: int | None = None
    fraction: float | None = None
    # The stage's own estimate, measured on this stage's work only (StageClock).
    remaining_seconds: float | None = None
    recent_asset_ids: list[str] = []
