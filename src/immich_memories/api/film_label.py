"""What Immich shows about an uploaded film: a description and tags (#2505).

One pure function builds both from the run's own facts, so the CLI, the web upload and the
automation retry cannot drift apart. The description is the film's title and its one-line
story summary; the tags (all under `immich-memories/`) file it by memory type, year and the
named occasions or trips in its plan. People get no tag: Immich's faces already say who is in a film.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

TAG_ROOT = "immich-memories"
DESCRIPTION_SEPARATOR = " · "
# The plan's occasions that name something the household would look for by name.
_NAMED_OCCASIONS = frozenset({"birthday", "visit", "trip", "leg"})


@dataclass(frozen=True)
class FilmLabel:
    """A film's Immich description and its tags beyond the provenance tag."""

    description: str | None = None
    tags: tuple[str, ...] = ()


def _name(value: Any) -> str:
    # "/" is Immich's level separator: a name carrying one would nest the tag.
    return " ".join(str(value or "").replace("/", "").split())


def _description(title: str, summary: str) -> str | None:
    if title and summary and title.casefold() != summary.casefold():
        return f"{title}{DESCRIPTION_SEPARATOR}{summary}"
    return title or summary or None


def _years(start: date | None, end: date | None) -> range:
    first, last = start or end, end or start
    return range(first.year, last.year + 1) if first and last else range(0)


def _story_names(episodes: Iterable[Mapping[str, Any]]) -> list[str]:
    names = []
    for episode in episodes:
        if episode.get("occasion") not in _NAMED_OCCASIONS:
            continue
        # A trip's legs are one story, filed under the trip's own name.
        trip = episode.get("trip")
        name = _name(trip if isinstance(trip, str) else None) or _name(episode.get("title"))
        if name:
            names.append(name)
    return list(dict.fromkeys(names))


def film_label(
    *,
    title: str | None,
    summary: str | None,
    type_label: str | None,
    date_start: date | None,
    date_end: date | None,
    episodes: Iterable[Mapping[str, Any]],
) -> FilmLabel:
    """The description and tags for one film.

    `episodes` are the plan's `story.episodes`; `summary` is its `story.thesis`.
    """
    tags = []
    if kind := _name(type_label):
        tags.append(f"{TAG_ROOT}/type/{kind}")
    tags += [f"{TAG_ROOT}/year/{year}" for year in _years(date_start, date_end)]
    tags += [f"{TAG_ROOT}/story/{name}" for name in _story_names(episodes)]
    return FilmLabel(
        description=_description(
            " ".join((title or "").split()), " ".join((summary or "").split())
        ),
        tags=tuple(tags),
    )
