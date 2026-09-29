"""What the finished film spends its seconds on: content, titles, and map time on top.

A trip's maps fly and then hold (6 to 8 s), where the card or title they replace
costs its regular length (the divider or title duration). The film's budget only
ever reserved the regular length, so the difference is extra: it goes on top of
the requested length rather than out of the pictures, and is reported as such.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from immich_memories.processing.assembly_config import AssemblyClip


@dataclass(frozen=True)
class FilmTimeline:
    """Seconds of content, of titles at their regular cost, and of map time past it."""

    content_seconds: float
    title_seconds: float
    map_extra_seconds: float

    def as_dict(self) -> dict[str, float]:
        """The rounded numbers a run record keeps."""
        return {key: round(value, 1) for key, value in asdict(self).items()}

    def describe(self) -> str:
        """One line for a log or a run summary."""
        return (
            f"{self.content_seconds:.1f}s content + {self.title_seconds:.1f}s titles"
            f" + {self.map_extra_seconds:.1f}s map extra"
        )


def _regular_seconds(clip: AssemblyClip, title_settings: Any) -> float | None:
    """What a map-capable screen costs in the budget, or None for any other clip."""
    if clip.asset_id == "title_screen":
        return float(title_settings.title_duration)
    if clip.asset_id.startswith("location_"):
        return float(title_settings.month_divider_duration)
    return None


def measure_film_timeline(final_clips: list[AssemblyClip], title_settings: Any) -> FilmTimeline:
    """Split a composed clip list into content, regular title time and map extra."""
    content = titles = extra = 0.0
    for clip in final_clips:
        if not clip.is_title_screen:
            content += clip.duration
            continue
        regular = _regular_seconds(clip, title_settings)
        over = max(0.0, clip.duration - regular) if regular is not None else 0.0
        titles += clip.duration - over
        extra += over
    return FilmTimeline(content, titles, extra)
