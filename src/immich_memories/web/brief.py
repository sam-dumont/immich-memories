"""A cut's brief from the web client: `generate`'s flags, one to one.

The page never builds its own request. It fills the same fields the terminal takes, the server
turns them into the `generate` command, and the page can show that command to copy. Every value
travels as `--flag=value`, one argv entry, so nothing a person types can become another option.
"""

from __future__ import annotations

import shlex
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

_VALUED = (
    "memory_type",
    "year",
    "month",
    "start",
    "end",
    "period",
    "season",
    "hemisphere",
    "holiday",
    "birthday",
    "people_expression",
    "person_match",
    "from_album",
    "day",
    "trip_index",
    "years_back",
    "near_date",
    "event_id",
    "duration",
    "photo_duration",
    "sharing",
)
_REPEATED = (("person", "--person"), ("include_asset", "--include"), ("exclude_asset", "--exclude"))


class CutBrief(BaseModel):
    """What to cut; None leaves a flag out, so the CLI's own default applies."""

    memory_type: str | None = None
    year: int | None = None
    month: int | None = None
    start: date | None = None
    end: date | None = None
    period: str | None = None
    season: Literal["spring", "summer", "fall", "autumn", "winter"] | None = None
    hemisphere: Literal["north", "south"] | None = None
    holiday: str | None = None
    birthday: str | None = None
    person: list[str] = []
    people_expression: str | None = None
    person_match: Literal["and", "or"] | None = None
    from_album: str | None = None
    day: date | None = None
    trip_index: int | None = None
    all_trips: bool = False
    years_back: int | None = None
    near_date: date | None = None
    event_id: str | None = None
    duration: int | None = None
    include_photos: bool | None = None
    include_live_photos: bool | None = None
    photo_duration: float | None = None
    accept_any_provenance: bool = False
    sharing: Literal["just-us", "family", "shareable"] | None = None
    include_asset: list[str] = []
    exclude_asset: list[str] = []

    def _flags(self) -> list[str]:
        flags = []
        for name in _VALUED:
            value = getattr(self, name)
            if value is not None:
                flags.append(f"--{name.replace('_', '-')}={value}")
        for name, flag in _REPEATED:
            flags.extend(f"{flag}={value}" for value in getattr(self, name))
        if self.all_trips:
            flags.append("--all-trips")
        if self.accept_any_provenance:
            flags.append("--accept-any-provenance")
        if self.include_photos is not None:
            flags.append("--include-photos" if self.include_photos else "--no-photos")
        if self.include_live_photos is not None:
            flags.append(
                "--include-live-photos" if self.include_live_photos else "--no-live-photos"
            )
        return flags

    def argv(self, *, executable: str, config: Path | None, output: Path) -> list[str]:
        """The command the server runs: this brief, cut and kept, rendered later."""
        head = [executable, *(["--config", str(config)] if config else []), "generate"]
        return [*head, *self._flags(), "--no-render", "--output", str(output)]

    def shown_command(self) -> str:
        """The same cut as a person would type it, without the server's own file choices."""
        return shlex.join(["immich-memories", "generate", *self._flags(), "--no-render"])
