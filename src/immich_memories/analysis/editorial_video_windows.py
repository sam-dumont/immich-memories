"""Which part of a kept video plays (#1949).

The editor chooses which videos make the film; this chooses where inside each one the hold
sits. Until the story-first route every clip was scored on its own segments; the route kept
the clip choice and lost that step, so every video played from its first frame and a finish
line showed the empty road before the riders.

A clear peak of change in the picture decides the window; without one, the speech does. The
facts are measured elsewhere (`editorial_clip_facts`); this module only chooses.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from operator import itemgetter
from typing import Protocol

from immich_memories.analysis.editorial_structure_budget import MIN_CARRIER_SECONDS
from immich_memories.speech.cuts import set_duration

# The step a window start moves in; half the activity bin, coarser than a frame.
STEP_SECONDS = 0.25
# A later window must beat the opening by this much: encoder noise alone never moves a cut.
CLEAR_MARGIN = 1.25
# The loudest rise is 1.0: a window must hold a clearly louder moment than the opening does.
SOUND_MARGIN = 0.3
# A cheer lands better after its build-up: "happy birthday to you", then the candles.
SOUND_LEAD_SECONDS = 1.5
# Speech is measured to the hundredth: half a second more of it is a reason to move.
SPEECH_MARGIN_SECONDS = 0.5
# Past the minimum hold a clip may be shaved from its end, so action there counts for less.
SHAVABLE_WEIGHT = 0.5


def _change(start: float, hold: float, probes, peak: float) -> float:
    sure_end, end = start + min(hold, MIN_CARRIER_SECONDS), start + hold
    return sum(
        (1.0 if t < sure_end else SHAVABLE_WEIGHT) * m / peak for t, m in probes if start <= t < end
    )


def _spoken(start: float, hold: float, speech) -> float:
    end = start + hold
    return sum(max(0.0, min(end, right) - max(start, left)) for left, right in speech)


def _excess(loudness) -> list[tuple[float, float]]:
    """How far each reading rises above the clip's own median, scaled to its loudest."""
    if not loudness:
        return []
    levels = sorted(db for _, db in loudness)
    middle = levels[len(levels) // 2]
    rises = [(t, max(0.0, db - middle)) for t, db in loudness]
    top = max(rise for _, rise in rises)
    return [(t, rise / top) for t, rise in rises] if top > 0 else []


def _heard(start: float, hold: float, rises) -> float:
    """The loudest rise the always-played part holds, plus how loud the hold is overall."""
    sure_end, end = start + min(hold, MIN_CARRIER_SECONDS), start + hold
    peak = max((r for t, r in rises if start <= t < sure_end), default=0.0)
    inside = [r for t, r in rises if start <= t < end]
    return peak + (sum(inside) / len(inside) if inside else 0.0) / 2


def _loudest(rises, *, duration: float, hold: float) -> float:
    """A start a moment before the loudest rise: the build-up, the cheer, and after."""
    top = max(rises, key=itemgetter(1))[0]
    return min(max(0.0, top - SOUND_LEAD_SECONDS), duration - hold)


def _best(starts, score) -> float:
    return max(starts, key=lambda s: (score(s), -s))


def choose_window(
    probes: Sequence[tuple[float, float]],
    *,
    duration: float,
    hold: float,
    speech: Sequence[tuple[float, float]] = (),
    loudness: Sequence[tuple[float, float]] = (),
) -> float:
    """The start, in source seconds, of the ``hold`` that shows the most of this clip.

    ``probes`` are (second, activity) readings of the picture, ``loudness`` (second, dB)
    readings of the sound, ``speech`` the measured utterances. A clear peak of change in
    the picture decides: from a still camera it is the action, and a crowd's PA heard all
    along must not pull a finish line off its riders. A handheld clip changes everywhere,
    so its sound decides next: the loudest moment (a cheer, the candles, a squeal) inside
    the part that always plays. Without either, the window holding the most speech wins, so
    a joke told on a walk starts on its first line. Otherwise the opening stays.
    """
    if duration <= hold:
        return 0.0
    starts = [i * STEP_SECONDS for i in range(int((duration - hold) / STEP_SECONDS) + 1)]
    peak = max((m for _, m in probes), default=0.0)
    rises = _excess(loudness)
    if peak > 0:
        seen = _best(starts, lambda s: _change(s, hold, probes, peak))
        if _change(seen, hold, probes, peak) > _change(0.0, hold, probes, peak) * CLEAR_MARGIN:
            return seen
    if rises:
        heard = _loudest(rises, duration=duration, hold=hold)
        if _heard(heard, hold, rises) > _heard(0.0, hold, rises) + SOUND_MARGIN:
            return heard
    if speech:
        spoken = _best(starts, lambda s: _spoken(s, hold, speech))
        if _spoken(spoken, hold, speech) >= _spoken(0.0, hold, speech) + SPEECH_MARGIN_SECONDS:
            return spoken
    return 0.0


class Facts(Protocol):
    @property
    def activity(self) -> Sequence[tuple[float, float]]: ...

    @property
    def loudness(self) -> Sequence[tuple[float, float]]: ...

    @property
    def speech(self) -> Sequence[tuple[float, float]]: ...


def place_windows(
    carriers: list[dict], facts_for: Callable[[str, float], Facts | None]
) -> list[dict]:
    """Start each kept video where its hold shows the most; every other carrier passes through.

    ``facts_for(asset_id, hold)`` answers what the clip shows and says. A video that already
    has a start (an owner's edit), plays whole, or could not be read keeps its interval.
    """
    placed = []
    for carrier in carriers:
        raw = float(carrier.get("raw_seconds") or 0.0)
        hold = carrier["seconds"]
        movable = carrier["kind"] == "video" and "start_time" not in carrier and raw > hold
        facts = facts_for(carrier["asset_id"], hold) if movable else None
        if facts is not None:
            start = choose_window(
                facts.activity,
                duration=raw,
                hold=hold,
                speech=facts.speech,
                loudness=facts.loudness,
            )
            carrier = carrier | {"start_time": start}
            set_duration(carrier, hold)
        placed.append(carrier)
    return placed
