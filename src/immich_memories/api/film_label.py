"""What Immich shows about an uploaded film: a description and tags (#2505).

One pure function builds both from the run's own facts, so the CLI, the web upload and the
automation retry cannot drift apart. The description is the film's title and its one-line
story summary; the tags (all under `immich-memories/`) file it by memory type, year and the
named occasions or trips in its plan. People get no tag: Immich's faces already say who is in a film.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
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


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _in_the_cut(episodes: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The episodes that put a shot in the film. A plan that never says (no `chosen`) shows all."""
    return [e for e in episodes if "chosen" not in e or e.get("chosen")]


def years_shown(
    episodes: Sequence[Mapping[str, Any]], start: date | None, end: date | None
) -> list[int]:
    """The years the stories with a shot in the film show; its window when none names a day.

    A birthdays film's windows reach years back, and the years it has no picture of are
    not years it is about.
    """
    years: set[int] = set()
    for episode in _in_the_cut(episodes):
        days = [d for d in map(_day, episode.get("days") or ()) if d]
        if days:
            years.update(_years(days[0], days[-1]))
    return sorted(years) or list(_years(start, end))


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


def provenance_tags(version: str | None, made_on: date | None) -> tuple[str, ...]:
    """Which release made a film, and the day it was made, beside the `generated` tag.

    A film's dates end on its last picture, so they never say when it was made or by which
    release. A run recorded before its release was kept gets no version tag.
    """
    tags = []
    if release := _name(version):
        tags.append(f"{TAG_ROOT}/version/{release}")
    if made_on is not None:
        tags.append(f"{TAG_ROOT}/generated-on/{made_on.isoformat()}")
    return tuple(tags)


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
    episodes = list(episodes)
    shown = _in_the_cut(episodes)
    tags = []
    if kind := _name(type_label):
        tags.append(f"{TAG_ROOT}/type/{kind}")
    tags += [f"{TAG_ROOT}/year/{year}" for year in years_shown(episodes, date_start, date_end)]
    tags += [f"{TAG_ROOT}/story/{name}" for name in _story_names(shown)]
    return FilmLabel(
        description=_description(
            " ".join((title or "").split()), " ".join((summary or "").split())
        ),
        tags=tuple(tags),
    )
