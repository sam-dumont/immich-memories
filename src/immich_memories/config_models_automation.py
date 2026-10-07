"""Configuration models for running unattended.

Which memories get detected without being asked for, and what happens to the
finished video: uploaded back to Immich, and reported on.
"""

from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel, Field, field_validator


class TripsConfig(BaseModel):
    """Trip detection configuration: homebase location and clustering thresholds."""

    homebase_latitude: float = Field(default=0.0, description="Home latitude (required for trips)")
    homebase_longitude: float = Field(
        default=0.0, description="Home longitude (required for trips)"
    )
    min_distance_km: float = Field(default=50, ge=1, description="Min km from home to count")
    min_duration_days: int = Field(default=2, ge=1, description="Min days to qualify as a trip")
    max_gap_days: int = Field(
        default=2, ge=1, description="Max calendar-day gap before splitting trips"
    )

    @property
    def hemisphere(self) -> str | None:
        """ "north" or "south" from the home base's latitude; None while it is unset (0,0)."""
        if self.homebase_latitude == self.homebase_longitude == 0.0:
            return None
        return "south" if self.homebase_latitude < 0 else "north"

    def validate_homebase(self) -> None:
        """Raise if homebase is still at Null Island (0,0)."""
        if self.homebase_latitude == self.homebase_longitude == 0.0:
            msg = (
                "Set your home coordinates in config "
                "(trips.homebase_latitude / trips.homebase_longitude)"
            )
            raise ValueError(msg)


class AutomationConfig(BaseModel):
    """Smart automation settings for candidate detection and auto-generation."""

    enabled: bool = Field(
        default=False,
        description="Run the daily auto-run decision inside the UI/Docker process",
    )
    daily_at: str = Field(
        default="09:00",
        description="Local wall-clock time (HH:MM) for the in-process daily run",
    )
    cooldown_hours: int = Field(default=24, ge=1, le=168)
    max_delivery_attempts: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Give up on an Immich upload after this many failed attempts",
    )
    upload_to_immich: bool = Field(default=False)
    album_name: str | None = Field(default=None)
    detect_monthly: bool = Field(default=True)
    detect_yearly: bool = Field(default=True)
    detect_trips: bool = Field(default=True)
    detect_person_spotlight: bool = Field(default=True)
    detect_activity_burst: bool = Field(default=True)
    burst_threshold: float = Field(default=2.0, ge=1.0, le=10.0)
    special_days_per_year: int = Field(
        default=6,
        ge=1,
        le=100,
        description=(
            "How many days a year discover-days keeps without a model, strongest first. "
            "A model reading names every occasion it finds"
        ),
    )
    accounts: list[str] = Field(
        default_factory=list,
        description=(
            "Extra Immich accounts (immich.accounts) automation reads alongside the "
            "primary, exactly as generate --accounts does. Empty reads the primary "
            "account alone, as before this setting existed."
        ),
    )
    detect_groups: bool = Field(
        default=True,
        description="Propose a memory for each saved people group (people group add) with content",
    )

    detect_seasons: bool = Field(
        default=True, description="Propose the season that just ended (needs the home base)"
    )
    detect_holidays: bool = Field(
        default=True, description="Propose a holiday film across the years with pictures around it"
    )
    detect_albums: bool = Field(
        default=True, description="Propose a film for a new Immich album, or one that has grown"
    )
    detect_person_monthly: bool = Field(
        default=True,
        description="Propose last month's film of each person close to you, from your people list",
    )
    backfill_months: bool = Field(
        default=True,
        description="Fill quiet nights with the months of this year and last that never got a film",
    )
    extra_holidays: list[str] = Field(
        default_factory=list,
        description='Days of your own to film as holidays, each written "MM-DD: name"',
    )
    include_shared_albums: bool = Field(
        default=False, description="Also propose albums other people shared with you"
    )

    @field_validator("extra_holidays")
    @classmethod
    def _check_extra_holidays(cls, value: list[str]) -> list[str]:
        for entry in value:
            match = re.fullmatch(r"(\d{2})-(\d{2}):\s*(\S.*)", entry.strip())
            if not match:
                raise ValueError(
                    f'extra_holidays entries look like "12-06: Saint Nicholas": {entry!r}'
                )
            try:
                date(2000, int(match[1]), int(match[2]))
            except ValueError as exc:
                raise ValueError(f"extra_holidays has no such day: {entry!r}") from exc
        return [entry.strip() for entry in value]

    @field_validator("daily_at")
    @classmethod
    def _normalize_daily_at(cls, value: str) -> str:
        match = re.fullmatch(r"(\d{1,2}):(\d{2})", value.strip())
        if not match or int(match[1]) > 23 or int(match[2]) > 59:
            raise ValueError("daily_at must be a 24h wall-clock time like '09:00'")
        return f"{int(match[1]):02d}:{match[2]}"


class NotificationConfig(BaseModel):
    """Apprise notification settings for job completion alerts."""

    enabled: bool = Field(default=False)
    urls: list[str] = Field(default_factory=list, description="Apprise notification URLs")
    on_success: bool = Field(default=True)
    on_failure: bool = Field(default=True)
    attach_thumbnail: bool = Field(
        default=False,
        description="Attach a generated video thumbnail to successful notifications",
    )
    cooldown_hours: int = Field(
        default=24,
        ge=1,
        le=168,
        description="Suppress normal delivery attempts after a notification failure",
    )


class UploadConfig(BaseModel):
    """Upload generated videos back to Immich."""

    enabled: bool = Field(default=False, description="Upload generated video to Immich")
    album_name: str | None = Field(
        default=None, description="Album name (created if missing, reused if exists)"
    )
