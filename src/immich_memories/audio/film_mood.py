"""A film's music mood from facts the run already has, with no model (#2471).

Without a text model every film used to get `calm`, the bottom of the energy scale, so a
birthday, a beach day and a quiet evening all got the same slow track. This reads what the
pipeline already knows about the film and picks from it:

- the memory type (a holiday, a special day, a trip, a season, a year in review);
- the stories the planner weighed (#2499): a birthday, a visit, a trip or its legs, an event;
- the season, from the film's most common month;
- how many shots move (videos and Live Photos that play);
- how many shots carry music in their own sound, and how many show a group of three or more.

A celebration or a trip starts lively; an ordinary month starts in the middle and moves with its
shots. Calm is kept for a quiet film: an ordinary period of still photos, no music, no group.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from immich_memories.audio.generators.ace_step_captions import MOOD_PROFILES
from immich_memories.audio.mood_analyzer import VideoMood

# Quiet to lively; a fact moves the film's mood along it.
_LADDER = ("calm", "peaceful", "tender", "playful", "happy", "exciting", "energetic")
# Stories that set the tone once the planner weighed them as the heart of the film.
_CENTRAL_WEIGHTS = frozenset({"dominant", "major"})
_CELEBRATION_TYPES = frozenset({"holiday", "special_day"})
_MOTION_KINDS = frozenset({"video", "live-motion", "motion"})
# A film this much in motion, or with this much music or company in it, reads livelier.
_LIVELY_MOTION = 0.35
_LIVELY_MUSIC = 0.2
_LIVELY_CROWD = 0.3
_QUIET_MOTION = 0.1
_GROUP_FACES = 3
_TEMPO = {"low": "slow", "medium": "medium", "high": "fast"}
_SEASONS = {
    12: "winter",
    1: "winter",
    2: "winter",
    3: "spring",
    4: "spring",
    5: "spring",
    6: "summer",
    7: "summer",
    8: "summer",
    9: "autumn",
    10: "autumn",
    11: "autumn",
}


@dataclass(frozen=True)
class FilmFacts:
    """What the film is, as counts and kinds: no names, places or ids."""

    memory_type: str | None = None
    # Occasions of the stories weighed dominant or major: birthday, visit, trip, leg, event.
    occasions: tuple[str, ...] = ()
    shots: int = 0
    moving: int = 0
    with_music: int = 0
    crowded: int = 0
    month: int | None = None
    hemisphere: str = "north"

    @property
    def season(self) -> str | None:
        if self.month is None:
            return None
        month = self.month
        if self.hemisphere.lower() == "south":
            month = (month + 5) % 12 + 1
        return _SEASONS[month]

    def share(self, count: int) -> float:
        return count / self.shots if self.shots else 0.0


@dataclass(frozen=True)
class RulesMood:
    """The mood the facts gave, and the facts that gave it, in words."""

    mood: VideoMood
    reasons: tuple[str, ...]


def read_plan(attempt: Path | None) -> dict[str, Any] | None:
    """The attempt's saved plan, or None when it left none behind."""
    if attempt is None:
        return None
    path = Path(attempt) / "plan.private.json"
    try:
        plan = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return plan if isinstance(plan, dict) else None


def facts_from_plan(
    plan: Mapping[str, Any] | None,
    *,
    memory_type: str | None = None,
    hemisphere: str = "north",
) -> FilmFacts:
    """Facts from the saved plan alone: its memory type, weighed stories and carriers."""
    plan = plan or {}
    carriers = [row for row in plan.get("carriers") or () if isinstance(row, Mapping)]
    return FilmFacts(
        memory_type=memory_type or _plan_memory_type(plan),
        occasions=_central_occasions(plan),
        shots=len(carriers),
        moving=sum(str(row.get("kind") or "") in _MOTION_KINDS for row in carriers),
        with_music=sum(bool(row.get("has_music")) for row in carriers),
        month=_common_month(str(row.get("taken") or "") for row in carriers),
        hemisphere=hemisphere,
    )


def facts_for_render(
    clips: Iterable[Any],
    plan: Mapping[str, Any] | None,
    *,
    memory_type: str | None,
    hemisphere: str = "north",
) -> FilmFacts:
    """Facts for the film being rendered: its clips, plus the plan's weighed stories."""
    shots = [clip for clip in clips if not getattr(clip, "is_title_screen", False)]
    planned = facts_from_plan(plan, memory_type=memory_type, hemisphere=hemisphere)
    if not shots:
        return planned
    return FilmFacts(
        memory_type=planned.memory_type,
        occasions=planned.occasions,
        shots=len(shots),
        moving=sum(not clip.is_photo for clip in shots),
        with_music=sum(bool(clip.has_music) for clip in shots),
        crowded=sum(len(clip.known_faces.faces) >= _GROUP_FACES for clip in shots),
        month=_common_month(str(clip.date or "") for clip in shots) or planned.month,
        hemisphere=hemisphere,
    )


def _plan_memory_type(plan: Mapping[str, Any]) -> str | None:
    policy = (plan.get("render_timing") or {}).get("policy") or {}
    value = policy.get("memory_type") if isinstance(policy, Mapping) else None
    return value if isinstance(value, str) and value else None


def _central_occasions(plan: Mapping[str, Any]) -> tuple[str, ...]:
    occasions: list[str] = []
    for story in (plan.get("story") or {}).get("episodes") or ():
        if not isinstance(story, Mapping) or story.get("weight") not in _CENTRAL_WEIGHTS:
            continue
        occasion = story.get("occasion") or ("trip" if story.get("kind") == "trip" else None)
        if isinstance(occasion, str) and occasion not in occasions:
            occasions.append(occasion)
    return tuple(occasions)


def _common_month(dates: Iterable[str]) -> int | None:
    months = Counter(date[5:7] for date in dates if len(date) >= 7 and date[5:7].isdigit())
    if not months:
        return None
    month = int(months.most_common(1)[0][0])
    return month if 1 <= month <= 12 else None


def _starting_point(facts: FilmFacts) -> tuple[str, str, bool]:
    """The mood the kind of film starts from, why, and whether it is an ordinary period."""
    kind, occasions = facts.memory_type, set(facts.occasions)
    if kind == "year_in_review":
        return "inspiring", "a year in review", False
    if kind in _CELEBRATION_TYPES or "birthday" in occasions:
        reason = "a birthday" if "birthday" in occasions else "a celebration"
        return "happy", reason, False
    if kind == "trip" or occasions & {"trip", "leg"}:
        return "happy", "a trip", False
    if occasions & {"visit", "event"}:
        return "playful", "a visit or an event", False
    if kind == "season":
        start = {"summer": "happy", "spring": "playful"}.get(facts.season or "", "tender")
        return start, f"a {facts.season or 'season'} film", False
    if kind in ("person_spotlight", "multi_person"):
        return "playful", "a film about people", False
    if kind == "on_this_day":
        return "tender", "this day over the years", True
    return "playful", "an ordinary period", True


def rules_mood(facts: FilmFacts) -> RulesMood:
    """Pick the film's mood from its facts alone."""
    start, reason, ordinary = _starting_point(facts)
    reasons = [reason]
    if start not in _LADDER:
        return RulesMood(_video_mood(start), tuple(reasons))
    step = _LADDER.index(start)
    motion = facts.share(facts.moving)
    company = facts.share(facts.with_music) >= _LIVELY_MUSIC or (
        facts.share(facts.crowded) >= _LIVELY_CROWD
    )
    if facts.shots:
        reasons.append(f"{facts.moving} of {facts.shots} shots move")
    if motion >= _LIVELY_MOTION:
        step += 1
    if company:
        step += 1
        reasons.append("music or a group in the shots")
    quiet = facts.shots > 0 and motion < _QUIET_MOTION and not company
    if quiet and ordinary:
        step = 0
    elif quiet:
        # A celebration or a trip in still photos is quieter, never calm.
        floor = _LADDER.index("playful") if start == "happy" else 1
        step = max(step - 1, floor)
    mood = _LADDER[min(step, len(_LADDER) - 1)]
    return RulesMood(_video_mood(mood), tuple(reasons))


def _video_mood(mood: str) -> VideoMood:
    energy = MOOD_PROFILES[mood].energy
    level = "low" if energy < 0.34 else "high" if energy > 0.7 else "medium"
    return VideoMood(primary_mood=mood, energy_level=level, tempo_suggestion=_TEMPO[level])


def fact_lines(facts: FilmFacts) -> list[str]:
    """The facts as prompt lines for the text model, the same ones the rules read."""
    lines: list[str] = []
    if facts.memory_type:
        lines.append(f"Memory type: {facts.memory_type.replace('_', ' ')}")
    if facts.occasions:
        lines.append(f"Main stories: {', '.join(facts.occasions)}")
    if facts.season:
        lines.append(f"Season: {facts.season}")
    if facts.shots:
        lines.extend(
            (
                f"Motion: {facts.moving} of {facts.shots} shots move (videos, Live Photos)",
                f"Music in the shots' own sound: {facts.with_music} of {facts.shots}",
            )
        )
        if facts.crowded:
            lines.append(f"Groups of three or more people: {facts.crowded} of {facts.shots}")
    return lines
