"""A dense one-off inside an ordinary day is its own story (no model).

At home the no-model reader groups a week's photographed days into one story. A one-off inside
one of those days (an evening across town photographed in two dense bursts) then shared the
week's single picture with the morning's errands. With no favourite on it nothing could lift it.

An episode of such a story is an event when every fact below agrees; none of them names a kind
of event, so a race, a concert, a graduation and a prize evening read the same:

- it is dense: its own pictures reach the day threshold the gate already uses for a whole day;
- it is more than one burst (`EVENT_MIN_BURSTS` moments), so a cake, a pet or a sunset shot fifty
  times in one go never qualifies;
- its activity label differs from every other episode of its day (or, alone on its day, from the
  episodes either side of it in the story), so a label alone never makes one;
- where both sides have GPS, it is at another place (`EVENT_MIN_KM` or more away).

Only stories below major are split: a story with three favourites or a big one already carries
the depth its event needs, and a trip carries its own. The event becomes its own story, funded
first among stories of its weight, reserving the minor word's two pictures.

A screen or document the next morning can add one picture, never make an event: when a picture
without a camera, taken in the `CORROBORATION_HOURS` after the event, reads a word that names a
result, a finish, a time or a rank (Immich's own OCR, through `printed_near`), the event reserves
three.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median
from typing import Any

from immich_memories.analysis.editorial_event_families import Point, _km

EVENT_MIN_BURSTS = 2
EVENT_MIN_KM = 1.0
EVENT_PICTURES = 2
CORROBORATION_HOURS = 18
# Words a screen or a document uses when it states an outcome; none belongs to one activity.
RESULT_WORDS = (
    "result",
    "results",
    "finish",
    "finisher",
    "time",
    "rank",
    "ranking",
    "position",
    "podium",
    "winner",
    "record",
    "score",
    "certificate",
    "award",
    "prize",
    "PR",
    "PB",
)

# (word, taken after, taken before) -> does a screen or document in that window read the word
PrintedNear = Callable[[str, datetime, datetime], bool]


@dataclass(frozen=True)
class EpisodeShape:
    """What the event rule reads of one episode."""

    day: str
    pictures: int
    bursts: int
    activity: str
    gps: Point | None
    end: datetime | None


def split_events(
    stories: list[dict[str, Any]],
    *,
    shape_of: Mapping[str, EpisodeShape],
    hints: Mapping[str, Mapping[str, Any]],
    title_of: Mapping[str, str],
    threshold: float,
    away: Callable[[Mapping[str, Any]], bool],
    printed_near: PrintedNear | None = None,
) -> list[dict[str, Any]]:
    """Take every event out of its story into a story of its own; returns one audit row each."""
    rows = []
    for story in list(stories):
        if len(story["episodes"]) < 2 or away(story) or _heavy(story):
            continue
        events = [k for k in story["episodes"] if _stands_out(k, story, shape_of, threshold)]
        for key in events:
            corroborated = _corroborated(shape_of[key], printed_near)
            event = _event_story(story, key, hints, title_of[key], corroborated)
            _without(story, key, hints, title_of)
            stories.insert(stories.index(story) + 1, event)
            rows.append({"story": event["key"], "from": story["key"], "corroborated": corroborated})
        if not story["episodes"]:
            stories.remove(story)
    return rows


def _heavy(story: Mapping[str, Any]) -> bool:
    return bool(story.get("big")) or story["seen"].get("favourites", 0) >= 3


def _stands_out(key, story, shape_of, threshold) -> bool:
    shape = shape_of[key]
    if shape.pictures < threshold or shape.bursts < EVENT_MIN_BURSTS or not shape.activity:
        return False
    ordered = sorted(story["episodes"], key=lambda k: (shape_of[k].day, k))
    at = ordered.index(key)
    others = [k for k in ordered if k != key and shape_of[k].day == shape.day] or [
        k
        for k in (
            ordered[at - 1] if at else None,
            ordered[at + 1] if at + 1 < len(ordered) else None,
        )
        if k
    ]
    for other in others:
        near = shape_of[other]
        if near.activity == shape.activity:
            return False
        if shape.gps and near.gps and _km(shape.gps, near.gps) < EVENT_MIN_KM:
            return False
    return True


def _corroborated(shape: EpisodeShape, printed_near: PrintedNear | None) -> bool:
    if printed_near is None or shape.end is None:
        return False
    until = shape.end + timedelta(hours=CORROBORATION_HOURS)
    return any(printed_near(word, shape.end, until) for word in RESULT_WORDS)


def _event_story(story, key, hints, title, corroborated) -> dict[str, Any]:
    hint = hints[key]
    return {
        "key": f"{story['key']}-{key}",
        "episodes": [key],
        "title": title,
        "purpose": "A one-off inside an ordinary day",
        "weight": "",
        "gate": hint.get("gate", "background"),
        "people_counts": dict(hint.get("relations", {})),
        "seen": {f: hint.get(f, 0) for f in ("moments", "pictures", "favourites")},
        "event": True,
        "reserve": EVENT_PICTURES + corroborated,
    }


def _without(story, key, hints, title_of) -> None:
    story["episodes"] = [k for k in story["episodes"] if k != key]
    keys = story["episodes"]
    relations: Counter[str] = Counter()
    for k in keys:
        relations.update(hints[k].get("relations", {}))
    story["people_counts"] = dict(relations)
    story["seen"] = {
        f: sum(hints[k].get(f, 0) for k in keys) for f in ("moments", "pictures", "favourites")
    }
    story["gate"] = min(
        (hints[k].get("gate", "background") for k in keys),
        key=("remarkable", "maybe", "background").index,
        default="background",
    )
    story["title"] = " / ".join(dict.fromkeys(title_of[k] for k in keys))


def episode_shapes(
    episodes: Sequence[Any],
    *,
    members_of: Callable[[Any], list[Any]],
    activity_of: Callable[[list[Any]], str],
    gps_of: Callable[[Any], Point | None],
) -> dict[str, EpisodeShape]:
    """The shape of every episode, from its pictures."""
    shapes = {}
    for episode in episodes:
        members = members_of(episode)
        points = [p for a in members if (p := gps_of(a)) is not None]
        taken = [a.file_created_at for a in members]
        shapes[episode.key] = EpisodeShape(
            day=min(taken).date().isoformat() if taken else "",
            pictures=len(members),
            bursts=len(episode.moments),
            activity=activity_of(members),
            gps=(median(p[0] for p in points), median(p[1] for p in points)) if points else None,
            end=max(taken) if taken else None,
        )
    return shapes
