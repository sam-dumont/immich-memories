"""Lay out a film without rendering its cards or opening media files."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from immich_memories.processing.assembly_config import (
    AssemblyClip,
    TitleScreenSettings,
    TransitionType,
)
from immich_memories.processing.assembly_engine import decide_transitions
from immich_memories.processing.film_timeline import measure_film_timeline
from immich_memories.processing.timeline_budget import TimelinePlan
from immich_memories.processing.title_divider_planner import TitleDividerPlanner
from immich_memories.processing.title_inserter import title_borrow
from immich_memories.titles.generator import GeneratedScreen


class _PreviewCards:
    """The divider planner only needs card paths; previews never open them."""

    def generate_month_divider(
        self, month: int, year: int | None = None, is_birthday_month: bool = False
    ) -> GeneratedScreen:
        return GeneratedScreen(Path(), 0, "month_divider")

    def generate_year_divider(self, year: int) -> GeneratedScreen:
        return GeneratedScreen(Path(), 0, "year_divider")

    def generate_location_card_screen(
        self, location_name: str, lat: float | None = None, lon: float | None = None
    ) -> GeneratedScreen:
        return GeneratedScreen(Path(), 0, "location")

    def generate_location_move_screen(
        self,
        location_name: str,
        came_from: tuple[float, float],
        destination: tuple[float, float],
        seconds: float,
    ) -> GeneratedScreen:
        return GeneratedScreen(Path(), seconds, "location")


def _open_with_title(sequence: list[AssemblyClip], duration: float, deblurs: bool) -> None:
    """Put the title first; one that deblurs into its clip plays that clip's opening."""
    first = next((i for i, clip in enumerate(sequence) if not clip.is_title_screen), None)
    if deblurs and first is not None:
        held = sequence[first]
        sequence[first] = replace(held, duration=held.duration - title_borrow(held.duration))
    sequence.insert(
        0,
        AssemblyClip(
            Path(),
            duration,
            asset_id="title_screen",
            is_title_screen=True,
            outgoing_transition="cut" if deblurs else None,
        ),
    )


def _close_with_ending(sequence: list[AssemblyClip], duration: float, deblurs: bool) -> None:
    """Put the ending last; one backed by the last clip plays that clip's close."""
    if sequence and deblurs:
        last = sequence[-1]
        tail = 0.0 if last.is_title_screen else title_borrow(last.duration)
        sequence[-1] = replace(last, duration=last.duration - tail, outgoing_transition="cut")
    sequence.append(AssemblyClip(Path(), duration, asset_id="ending_screen", is_title_screen=True))


def _opening_seconds(titles: TitleScreenSettings, plan: TimelinePlan) -> float:
    """The title's planned length, or the trip's fly-over when it opens on one.

    The same condition as assembly's (a trip with stops, a title and a home to leave from,
    with map tiles allowed), and the same length: a map move from home to the stops.
    """
    home = (titles.home_lat, titles.home_lon)
    if not (
        titles.memory_type == "trip"
        and titles.map_tiles
        and titles.trip_locations
        and titles.trip_title_text
        and home[0] is not None
        and home[1] is not None
    ):
        return plan.title_duration
    return titles.map_move.intro_seconds((home[0], home[1]), titles.trip_locations)


def _composed(
    clips: list[AssemblyClip], plan: TimelinePlan, titles: TitleScreenSettings
) -> tuple[list[AssemblyClip], TitleScreenSettings]:
    """The sequence assembly will compose, and the title settings the plan sized it with."""
    total = sum(clip.duration for clip in clips)
    ratio = min(1.0, plan.content_budget / total) if total > 0 else 1.0
    content = [replace(clip, duration=clip.duration * ratio) for clip in clips]
    settings = replace(
        titles,
        title_duration=plan.title_duration,
        month_divider_duration=plan.divider_duration,
        max_dividers=plan.max_dividers,
    )
    sequence = TitleDividerPlanner(_PreviewCards(), settings).select_divider_strategy(
        content, None, titles.memory_type == "trip"
    )
    content_backed = titles.title_background == "content_backed"
    if plan.title_duration > 0:
        map_intro = titles.memory_type == "trip" and any(c.latitude is not None for c in content)
        _open_with_title(sequence, _opening_seconds(titles, plan), content_backed and not map_intro)
    if plan.ending_duration > 0:
        _close_with_ending(sequence, plan.ending_duration, content_backed)
    return sequence, settings


def preview_map_extra(
    clips: list[AssemblyClip], plan: TimelinePlan, titles: TitleScreenSettings
) -> float:
    """Seconds the film's maps run past the title and cards they replace (on top of the film)."""
    sequence, settings = _composed(clips, plan, titles)
    return measure_film_timeline(sequence, settings).map_extra_seconds


def preview_timeline(
    clips: list[AssemblyClip],
    plan: TimelinePlan,
    titles: TitleScreenSettings,
    transition: str,
    transition_duration: float,
) -> tuple[dict[str, tuple[float, float]], float]:
    """Content starts and holds, plus film length, using the assembler's boundary policy."""
    sequence, _ = _composed(clips, plan, titles)
    transitions = decide_transitions(sequence, TransitionType(transition), transition_duration)
    positions = {}
    start = 0.0
    for index, clip in enumerate(sequence):
        if not clip.is_title_screen:
            positions[clip.asset_id] = (start, clip.duration)
        start += clip.duration
        if index < len(transitions) and transitions[index] == "fade":
            start -= transition_duration
    return positions, max(0.0, start)
