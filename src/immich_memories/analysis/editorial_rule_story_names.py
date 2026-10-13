"""The rules reader's stories as a person names them: occasions out, every story called (#2486).

Two passes over the stories `RuleStructureReader._stories` built:

- `take_out_occasions` moves each day the household keeps (`editorial_occasions`) out of its
  week at home into a story of its own, named and purposed from its facts;
- `name_stories` gives every other story its name, purpose and facts
  (`editorial_story_names`): a trip and its legs, a day, or days at home.

Every story then carries what the summary and the titles read (#2488, #2489): `occasion`,
`people`, `days`, `places` and `trip`, beside the title and purpose it always had.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from immich_memories.analysis.editorial_occasions import Occasion
from immich_memories.analysis.editorial_story_names import (
    home_name,
    leg_name,
    outing_name,
    trip_name,
    trip_purpose,
)
from immich_memories.analysis.editorial_story_replies import WEIGHTS

_SEEN = ("moments", "pictures", "favourites")
_GATES = ("remarkable", "maybe", "background")
# What the household keeps outweighs the days around it: an occasion or a trip is at least major.
OCCASION_WEIGHT = "major"


@dataclass(frozen=True)
class StoryFacts:
    """What a story's own pictures say, for its name."""

    days: tuple[str, ...]
    places: tuple[str, ...]
    people: tuple[str, ...]
    album: str | None
    farthest: str | None
    reach_km: float | None = None


def take_out_occasions(
    stories: list[dict[str, Any]],
    occasions: Mapping[str, Occasion],
    *,
    day_of: Mapping[str, str],
    hints: Mapping[str, Mapping[str, Any]],
    away: Callable[[Mapping[str, Any]], bool],
) -> list[dict[str, Any]]:
    """Give each occasion day at home a story of its own; returns one audit row each."""
    rows = []
    for story in stories.copy():
        if away(story):
            continue
        for day, occasion in sorted(occasions.items()):
            keys = [k for k in story["episodes"] if day_of[k] == day]
            if not keys:
                continue
            target = story
            if len(keys) < len(story["episodes"]):
                target = _taken_out(story, keys, hints, day)
                story["episodes"] = [k for k in story["episodes"] if k not in keys]
                _restate(story, hints)
                stories.insert(stories.index(story) + 1, target)
            target.update(
                title=occasion.name,
                purpose=occasion.purpose,
                occasion=occasion.kind,
                people=list(occasion.people),
            )
            rows.append({"story": target["key"], "day": day, "occasion": occasion.kind})
    return rows


def _taken_out(story, keys, hints, day) -> dict[str, Any]:
    taken = {"key": f"{story['key']}-{day}", "episodes": list(keys), "weight": ""}
    _restate(taken, hints)
    return taken


def _restate(story: dict[str, Any], hints: Mapping[str, Mapping[str, Any]]) -> None:
    keys = story["episodes"]
    relations: Counter[str] = Counter()
    for k in keys:
        relations.update(hints[k].get("relations", {}))
    story["people_counts"] = dict(relations)
    story["seen"] = {f: sum(hints[k].get(f, 0) for k in keys) for f in _SEEN}
    story["gate"] = min(
        (hints[k].get("gate", "background") for k in keys), key=_GATES.index, default="background"
    )


def name_stories(
    stories: Sequence[dict[str, Any]],
    *,
    facts_of: Callable[[Mapping[str, Any]], StoryFacts],
    away: Callable[[Mapping[str, Any]], bool],
    trip_rule: tuple[float, int],
) -> None:
    """Name every story the occasions left unnamed; a run of stories away is one trip's legs.

    `trip_rule` is the install's own trip: at least so many km from home, over at least so
    many days (`trips.min_distance_km`, `trips.min_duration_days`). A stay away short of it is
    a day out, named like one: an evening concert 11 km off is no "Trip to Tervuren".
    """
    named: set[int] = set()
    for run in _trips(stories, away, facts_of):
        named.update(id(story) for story, _ in run)
        facts = [fact for _, fact in run]
        if _is_trip(facts, trip_rule):
            _name_trip([story for story, _ in run], facts)
        else:
            for story, fact in run:
                _set(story, fact, *outing_name(fact.days, fact.places), None)
    for story in stories:
        if id(story) in named:
            continue
        own = facts_of(story)
        if "occasion" in story:
            # Named by `take_out_occasions`; it still carries its facts like any other story.
            _set(story, own, story["title"], story["purpose"], story["occasion"])
            story["people"] = list(dict.fromkeys([*story["people"], *own.people]))
            continue
        name, purpose = home_name(own.days, own.places)
        _set(story, own, name, purpose, "event" if story.get("event") else None)


def _trips(stories, away, facts_of) -> list[list[tuple[dict[str, Any], StoryFacts]]]:
    """Stories away with their facts, grouped into runs of unbroken days.

    The reader lists a stretch's days at home before its days away, so two stays away either
    side of a day at home sit next to each other in the list; only the calendar joins legs.
    """
    placed = sorted(
        (
            (story, fact)
            for story in stories
            if "occasion" not in story and away(story) and (fact := facts_of(story)).days
        ),
        key=lambda row: row[1].days[0],
    )
    trips: list[list[tuple[dict[str, Any], StoryFacts]]] = []
    for story, fact in placed:
        if trips and _next_day(trips[-1][-1][1].days[-1]) >= fact.days[0]:
            trips[-1].append((story, fact))
        else:
            trips.append([(story, fact)])
    return trips


def _next_day(day: str) -> str:
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


def _is_trip(facts: Sequence[StoryFacts], trip_rule: tuple[float, int]) -> bool:
    min_km, min_days = trip_rule
    days = sorted({day for fact in facts for day in fact.days})
    if not days:
        return False
    length = (date.fromisoformat(days[-1]) - date.fromisoformat(days[0])).days + 1
    reach = max((f.reach_km for f in facts if f.reach_km is not None), default=None)
    # Without a home to measure from, a stay away long enough is a trip, as it always was.
    return length >= min_days and (reach is None or reach >= min_km)


def _name_trip(legs: list[dict[str, Any]], facts: Sequence[StoryFacts]) -> None:
    albums = Counter(f.album for f in facts if f.album)
    farthest = next((f.farthest for f in facts if f.farthest), None)
    whole = trip_name(album=albums.most_common(1)[0][0] if albums else None, farthest=farthest)
    for leg, fact in zip(legs, facts, strict=True):
        name = leg_name(fact.places, trip=whole, legs=len(legs))
        _set(
            leg,
            fact,
            name,
            trip_purpose(fact.days, fact.places),
            "trip" if len(legs) == 1 else "leg",
        )
        leg["trip"] = whole


def _set(story, facts: StoryFacts, name: str, purpose: str, occasion: str | None) -> None:
    story.update(
        title=name,
        purpose=purpose,
        occasion=occasion,
        people=list(facts.people),
        days=[min(facts.days), max(facts.days)] if facts.days else [],
        places=list(facts.places),
    )
    story.setdefault("trip", None)


def raise_kept_days(stories: Sequence[dict[str, Any]]) -> list[str]:
    """An occasion, or a trip as a whole, weighs at least `OCCASION_WEIGHT`; returns the raised."""
    raised = []
    for story in stories:
        if story.get("occasion") not in ("birthday", "visit", "trip"):
            continue
        weight = story.get("weight") or "none"
        if WEIGHTS.index(weight) > WEIGHTS.index(OCCASION_WEIGHT):
            story["weight"] = OCCASION_WEIGHT
            raised.append(story["key"])
    return raised
