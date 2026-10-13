"""What the cut's own stories tell the title: their names, biggest first, and the summary.

The planner writes every story it weighed into the attempt's plan
(`plan["story"]["episodes"]`). The title reads them back from there, so a summer
that held a birthday and a road trip is named from those, not from whichever
album most of its pictures happen to sit in. Fields a planner has not written yet
read as absent: an old plan still titles, it just tells the model less.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Heaviest first; a story the planner gave no weight is not in the film.
_WEIGHT_ORDER = ("dominant", "major", "minor", "glimpse")
_MOST_STORIES = 6
_MOST_SUMMARY_CHARS = 400
_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class FilmStory:
    """One story the cut tells, as far as the title may use it."""

    name: str
    weight: str
    purpose: str = ""
    occasion: str | None = None
    people: tuple[str, ...] = ()
    days: tuple[str, ...] = ()
    places: tuple[str, ...] = ()

    def fact_line(self) -> str:
        """The story as one fact line: its name, then what the record says about it."""
        notes = [self.weight]
        if self.occasion:
            notes.append(self.occasion)
        if self.days:
            notes.append(" to ".join(dict.fromkeys(self.days)))
        if self.places:
            notes.append("at " + ", ".join(self.places[:4]))
        if self.people:
            notes.append("with " + ", ".join(self.people[:4]))
        line = f"{self.name} ({'; '.join(notes)})"
        return f"{line}: {self.purpose}" if self.purpose else line


@dataclass(frozen=True)
class FilmStories:
    """The cut's stories, heaviest first, and its summary when the run wrote one."""

    stories: tuple[FilmStory, ...] = ()
    summary: str | None = None

    @property
    def lead(self) -> FilmStory | None:
        return self.stories[0] if self.stories else None


def _texts(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(text for item in value if (text := str(item or "").strip()))


def _is_a_name(title: str) -> bool:
    """A story's name, not the label list or bare date an older planner wrote in its place."""
    return bool(title) and " / " not in title and not _ISO_DAY.match(title)


def _story(row: Mapping[str, Any]) -> FilmStory | None:
    weight = str(row.get("weight") or "")
    trip = str(row.get("trip") or "").strip()
    name = trip or str(row.get("title") or "").strip()
    if weight not in _WEIGHT_ORDER or not _is_a_name(name) or row.get("granted") == 0:
        return None
    occasion = row.get("occasion")
    return FilmStory(
        name=name,
        weight=weight,
        purpose="" if trip else str(row.get("purpose") or "").strip(),
        occasion="trip" if trip else (str(occasion) if occasion else None),
        people=_texts(row.get("people")),
        days=_texts(row.get("days")),
        places=_texts(row.get("places")),
    )


def _merged(first: FilmStory, other: FilmStory) -> FilmStory:
    """A trip's legs as the one trip: its heaviest weight, every place and day it reached."""
    days = sorted({*first.days, *other.days})
    return FilmStory(
        name=first.name,
        weight=min(first.weight, other.weight, key=_WEIGHT_ORDER.index),
        purpose=first.purpose,
        occasion=first.occasion,
        people=tuple(dict.fromkeys((*first.people, *other.people))),
        days=(days[0], days[-1]) if days else (),
        places=tuple(dict.fromkeys((*first.places, *other.places))),
    )


def ranked_stories(rows: Iterable[Mapping[str, Any]]) -> tuple[FilmStory, ...]:
    """The named stories in the cut, heaviest first, a trip's legs folded into the trip."""
    by_name: dict[str, FilmStory] = {}
    for row in rows:
        if not isinstance(row, Mapping) or (story := _story(row)) is None:
            continue
        known = by_name.get(story.name)
        by_name[story.name] = story if known is None else _merged(known, story)
    ordered = sorted(by_name.values(), key=lambda s: _WEIGHT_ORDER.index(s.weight))
    return tuple(ordered[:_MOST_STORIES])


def film_stories_from_plan(plan: Mapping[str, Any]) -> FilmStories:
    """The stories and summary an attempt's plan records."""
    story = plan.get("story") or {}
    if not isinstance(story, Mapping):
        return FilmStories()
    # The film's summary is the story's thesis, final once the cut is summarised.
    summary = str(story.get("thesis") or "").strip()
    return FilmStories(
        stories=ranked_stories(story.get("episodes") or ()),
        summary=summary[:_MOST_SUMMARY_CHARS] or None,
    )


def read_film_stories(attempt_dir: Path | str | None) -> FilmStories:
    """The stories an attempt directory's plan records, or none when it left no plan."""
    from immich_memories.operations.storyboard import PLAN_FILE

    if attempt_dir is None:
        return FilmStories()
    try:
        plan = json.loads((Path(attempt_dir) / PLAN_FILE).read_text())
    except (OSError, ValueError):
        logger.debug("No readable plan for the title's stories", exc_info=True)
        return FilmStories()
    return film_stories_from_plan(plan) if isinstance(plan, Mapping) else FilmStories()
