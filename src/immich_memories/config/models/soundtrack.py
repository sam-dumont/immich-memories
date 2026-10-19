"""Configuration models for the music under a memory.

A local library to pick from, or one of the two generators that write a track
for the video instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, Field, field_validator

from immich_memories.config.models.resources import http_url_or_blank


class AudioConfig(BaseModel):
    """Soundtrack policy: whether films get music, your own music folder, and how
    auto-generated music is vetted.

    Generation picks its backend from `ace_step.enabled` / `musicgen.enabled`
    and the `--music` / `--no-music` flags; ducking and fades are fixed in the
    mixer.
    """

    no_music: bool = Field(
        default=False,
        description=(
            "Render films without music unless a run asks for it (`--music`, or a "
            "track picked in the web render panel); automation follows it too"
        ),
    )
    local_music_dir: str = Field(
        default="~/Music/Memories",
        description=(
            "Your own music, one subfolder per mood like the bundled tracks. Films pick "
            "from it by mood before the bundled tracks; a mood it lacks plays bundled ones"
        ),
    )
    max_regenerations: int = Field(
        default=2,
        ge=0,
        le=3,
        description="Ignored: generated music is one take and is never regenerated",
    )
    # Takes of up to 90 s joined on bar lines are the production recipe; one take per
    # film of any length sounded bland and loop-flagged (#2617).
    music_block_seconds: int = Field(
        default=90,
        ge=30,
        le=300,
        description=(
            "Longest single ACE-Step take before auto mode joins several. A film "
            "longer than this gets takes that share one caption, tempo and key, "
            "joined on bar lines"
        ),
    )
    max_music_blocks: int = Field(
        default=3,
        ge=1,
        le=6,
        description=(
            "Takes to join for a film longer than music_block_seconds; beyond this the takes repeat"
        ),
    )

    @property
    def local_music_path(self) -> Path:
        """Get the expanded local music directory path."""
        return Path(self.local_music_dir).expanduser()


class MusicGenConfig(BaseModel):
    """Settings for AI music generation via MusicGen API."""

    ENV_REFERENCE_FIELDS: ClassVar[frozenset[str]] = frozenset({"api_key", "base_url"})

    enabled: bool = Field(
        default=False,
        description="Enable AI music generation using MusicGen API",
    )
    base_url: str = Field(
        default="http://localhost:8000",
        description="MusicGen API server URL",
    )
    api_key: str = Field(
        default="",
        description="MusicGen API key for authentication",
    )
    timeout_seconds: int = Field(
        default=10800,  # 3 hours
        ge=60,
        le=18000,  # Up to 5 hours max
        description="Maximum time to wait per music generation job (seconds)",
    )
    num_versions: int = Field(
        default=3,
        ge=1,
        le=5,
        description="Number of music versions to generate for selection",
    )
    hemisphere: str = Field(
        default="north",
        description="Hemisphere for seasonal music prompts ('north' or 'south')",
    )

    _http_url = field_validator("base_url")(http_url_or_blank)


class ACEStepConfig(BaseModel):
    """Settings for ACE-Step music generation.

    ACE-Step 1.5 can run locally as a Python library (preferred for desktop)
    or via a remote Gradio API server.
    """

    ENV_REFERENCE_FIELDS: ClassVar[frozenset[str]] = frozenset({"api_url", "api_key"})

    enabled: bool = Field(
        default=False,
        description="Enable ACE-Step music generation",
    )
    mode: Literal["lib", "api"] = Field(
        default="api",
        description="Generation mode: 'api' for remote REST server (default), 'lib' for local library (requires Python 3.12)",
    )
    api_url: str = Field(
        default="http://localhost:8000",
        description="ACE-Step REST API server URL (only used in API mode)",
    )
    api_key: str = Field(
        default="",
        description="API key for ACE-Step server authentication (optional)",
    )
    model_variant: str = Field(
        default="auto",
        description=(
            "ACE-Step DiT model. 'auto' loads the 4B XL turbo model on a Mac with 64 GB "
            "or more of unified memory or a GPU with 16 GB or more, and the 2B 'turbo' "
            "below that, falling back to 2B if XL fails to load. 'turbo'/'base' pin the "
            "2B family; 'xl-turbo' pins the 4B XL model"
        ),
    )
    lm_model_size: str = Field(
        default="1.7B",
        description="Language model size: '0.6B', '1.7B', or '4B'",
    )
    use_lm: bool = Field(
        default=False,
        description=(
            "Use the 5Hz language model's 'thinking mode'. Off by default: it rewrites "
            "the caption and invents its own genre metadata, which drifts instrumental "
            "prompts off-brief, and it dominates generation time (~45s -> ~17s per "
            "60s track when disabled). Enable for prompt-following on complex briefs. In API "
            "mode, off also tells the server to skip its planner and keep the caption."
        ),
    )
    cpu_offload: bool = Field(
        default=True,
        description=(
            "Move local CUDA music models back to CPU between phases to reduce VRAM use. "
            "False keeps them on CUDA for speed when memory permits. Ignored by the "
            "Apple Silicon runtime and API mode; the host memory guard still applies."
        ),
    )
    num_versions: int = Field(
        default=3,
        ge=1,
        le=5,
        description="Number of music versions to generate for selection",
    )
    hemisphere: str = Field(
        default="north",
        description="Hemisphere for seasonal music prompts ('north' or 'south')",
    )
    timeout_seconds: int = Field(
        default=3600,
        ge=60,
        le=18000,
        description="Maximum time per generation job (seconds)",
    )

    _http_url = field_validator("api_url")(http_url_or_blank)
