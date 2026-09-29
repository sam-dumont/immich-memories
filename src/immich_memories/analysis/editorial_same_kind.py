"""A recurring kind inside one partition is one story's worth of pictures (no model).

The no-model reader weighs every story with three favourites major, and every major story deepens
to the same level. Three starred evenings of the same activity at the same place in one month
then took three times the depth of a ten-day trip. The model tier folds such stories into a
thread after asking; the no-model tier asks nothing, so it reads the same thing from facts.

Two stories are the same kind when the densest episode of each carries the same activity label
AND the label is backed by two facts: that episode alone reaches the day threshold the gate
already uses (a label on three pictures says nothing), and both happen at one place (medians of
their GPS within `NEAR_KM`, or the same place name when a side has no GPS). They must fall in the
same partition of the film, the film itself when it has none. Trips (a story away from home)
and big stories (dense and full of close family) never fold: they carry their own weight.

A kind keeps every member's own picture; its further depth goes to its heaviest member (most
favourites, then most moments, then the earliest), marked `depth_to` on every member.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from immich_memories.analysis.editorial_event_families import NEAR_KM, Point, _km


@dataclass(frozen=True)
class EpisodeKind:
    """What the kind rule reads of one episode."""

    pictures: int
    activity: str
    place: str
    gps: Point | None
    partition: str | None


def _near(a: EpisodeKind, b: EpisodeKind) -> bool:
    if a.gps is not None and b.gps is not None:
        return _km(a.gps, b.gps) <= NEAR_KM
    return bool(a.place) and a.place == b.place


def same_kind_threads(
    stories: Sequence[dict[str, Any]],
    *,
    kind_of: Mapping[str, EpisodeKind],
    threshold: float,
    away: Callable[[Mapping[str, Any]], bool],
) -> list[dict[str, Any]]:
    """Mark each story of a recurring kind with `depth_to`, its kind's depth holder.

    Returns one audit row per kind found.
    """
    candidates: list[tuple[dict[str, Any], EpisodeKind]] = []
    for story in stories:
        if story.get("weight") in ("", "none", "glimpse") or story.get("big") or away(story):
            continue
        densest = max(story["episodes"], key=lambda key: kind_of[key].pictures)
        kind = kind_of[densest]
        if kind.activity and kind.pictures >= threshold:
            candidates.append((story, kind))
    activity = {id(story): kind.activity for story, kind in candidates}
    rows = []
    for group in _linked(candidates):
        holder = min(
            group,
            key=lambda s: (
                -s["seen"].get("favourites", 0),
                -s["seen"].get("moments", 0),
                stories.index(s),
            ),
        )
        for story in group:
            story["depth_to"] = holder["key"]
        rows.append(
            {
                "depth_to": holder["key"],
                "members": [s["key"] for s in group],
                "kind": activity[id(holder)],
            }
        )
    return rows


def _linked(candidates: list[tuple[dict[str, Any], EpisodeKind]]) -> list[list[dict[str, Any]]]:
    parent = list(range(len(candidates)))

    def root(i: int) -> int:
        while parent[i] != i:
            i = parent[i]
        return i

    for i, (_, a) in enumerate(candidates):
        for j in range(i + 1, len(candidates)):
            b = candidates[j][1]
            if a.activity == b.activity and a.partition == b.partition and _near(a, b):
                parent[root(j)] = root(i)
    groups: dict[int, list[dict[str, Any]]] = {}
    for i, (story, _) in enumerate(candidates):
        groups.setdefault(root(i), []).append(story)
    return [members for members in groups.values() if len(members) > 1]
