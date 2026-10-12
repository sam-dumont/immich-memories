"""Which part of a kept video plays (#1949).

The editor chooses which videos make the film; this chooses where inside each one the hold
sits. Until the story-first route every clip was scored on its own segments; the route kept
the clip choice and lost that step, so every video played from its first frame and a finish
line showed the empty road before the riders.

A clear peak of change in the picture decides the window; without one, the speech does. The
facts are measured elsewhere (`editorial_clip_facts`); this module only chooses.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from operator import itemgetter
from typing import Protocol

from immich_memories.analysis.editorial_structure_budget import (
    LONGEST_EXCHANGE_SECONDS,
    MIN_CARRIER_SECONDS,
)
from immich_memories.speech.cuts import safe_end, set_duration

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
# #2022: a flagged second inside a candidate window costs this much of a second of score,
# so a window that holds a flagged moment loses to an equally-busy one that does not. When
# every window is equally flagged the penalty is the same everywhere and changes nothing,
# so the clip keeps today's choice rather than being pushed somewhere arbitrary.
OBSTRUCTION_PENALTY_SECONDS = 0.5


def _change(start: float, hold: float, probes, peak: float) -> float:
    sure_end, end = start + min(hold, MIN_CARRIER_SECONDS), start + hold
    return sum(
        (1.0 if t < sure_end else SHAVABLE_WEIGHT) * m / peak for t, m in probes if start <= t < end
    )


def _obstruction_penalty(start: float, hold: float, obstructed: Sequence[float]) -> float:
    flagged_inside = sum(1 for second in obstructed if start <= second < start + hold)
    return OBSTRUCTION_PENALTY_SECONDS * flagged_inside


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
    obstructed: Sequence[float] = (),
) -> float:
    """The start, in source seconds, of the ``hold`` that shows the most of this clip.

    ``probes`` are (second, activity) readings of the picture, ``loudness`` (second, dB)
    readings of the sound, ``speech`` the measured utterances, ``obstructed`` the seconds a
    finger-over-the-lens check flagged (#2022). A clear peak of change in the picture
    decides: from a still camera it is the action, and a crowd's PA heard all along must not
    pull a finish line off its riders. A handheld clip changes everywhere, so its sound
    decides next: the loudest moment (a cheer, the candles, a squeal) inside the part that
    always plays. Without either, the window holding the most speech wins, so a joke told on
    a walk starts on its first line. Otherwise the opening stays. Among windows that would
    otherwise tie, one holding fewer flagged seconds wins; flagged everywhere, the penalty
    is everywhere the same and today's choice stands.
    """
    if duration <= hold:
        return 0.0
    starts = [i * STEP_SECONDS for i in range(int((duration - hold) / STEP_SECONDS) + 1)]
    peak = max((m for _, m in probes), default=0.0)
    rises = _excess(loudness)
    if peak > 0:

        def scored(s: float) -> float:
            return _change(s, hold, probes, peak) - _obstruction_penalty(s, hold, obstructed)

        seen = _best(starts, scored)
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

    @property
    def obstructed(self) -> Sequence[float]: ...


def grow_holds(
    carriers: list[dict],
    spare_seconds: float,
    *,
    era_of: Callable[[str], str | None] | None = None,
) -> list[dict]:
    """A short film's kept videos hold longer, towards the content it still has unspent (#2090).

    The film's videos were all cut at the motion cap before anyone looked at what the film had
    room for. With ``spare_seconds`` of its content budget unspent, each video that can still
    play (its own source is longer, no owner edit fixed its interval) takes an equal share, up
    to ``LONGEST_EXCHANGE_SECONDS``. This runs before the window is placed, so a window
    against the end of its source grows backwards from the last frame.

    ``era_of`` (a capture time's era) bounds a film about the dates: no era grows past an
    even share of the content, so one year's long videos never take the time the other years
    had no video to fill.
    """
    grown = [c.copy() for c in carriers]
    era_room = _era_room(grown, spare_seconds, era_of)

    def room(i: int) -> float:
        own = min(float(grown[i]["raw_seconds"]), LONGEST_EXCHANGE_SECONDS) - grown[i]["seconds"]
        if era_of is None:
            return own
        return min(own, era_room.get(era_of(str(grown[i]["taken"])), 0.0))

    growable = [
        i
        for i, c in enumerate(grown)
        if c["kind"] == "video" and "start_time" not in c and room(i) > 1e-6
    ]
    while spare_seconds > 1e-6 and growable:
        share = spare_seconds / len(growable)
        for i in growable:
            step = min(share, room(i))
            grown[i]["seconds"] = grown[i]["seconds"] + step
            spare_seconds -= step
            if era_of is not None:
                era = era_of(str(grown[i]["taken"]))
                era_room[era] = era_room.get(era, 0.0) - step
        growable = [i for i in growable if room(i) > 1e-6]
    return grown


def _era_room(
    carriers: list[dict], spare_seconds: float, era_of: Callable[[str], str | None] | None
) -> dict[str | None, float]:
    """The seconds each era may still grow by: an even share of the content, less what it holds."""
    if era_of is None:
        return {}
    held: dict[str | None, float] = {}
    for c in carriers:
        era = era_of(str(c["taken"]))
        held[era] = held.get(era, 0.0) + float(c["seconds"])
    share = (sum(held.values()) + spare_seconds) / max(1, len(held))
    return {era: max(0.0, share - seconds) for era, seconds in held.items()}


def within_era_shares(
    carriers: list[dict],
    before: Mapping[str, float],
    content_seconds: float,
    era_of: Callable[[str], str | None],
) -> list[dict]:
    """Hand back what speech added past an era's even share of a film about the dates.

    Finishing a sentence grew one year's video of a holiday film to 11.5 s, and the fit then
    dropped another year's shot to make room. A clip that speech lengthened (`before` holds
    its hold from before) gives the excess back, ending before the sentence it would cut, and
    never below the hold the editor chose.
    """
    held: dict[str | None, float] = {}
    for c in carriers:
        era = era_of(str(c["taken"]))
        held[era] = held.get(era, 0.0) + float(c["seconds"])
    share = content_seconds / max(1, len(held))
    fitted = []
    for original in carriers:
        carrier = original.copy()
        era = era_of(str(carrier["taken"]))
        chosen = before.get(carrier["asset_id"], carrier["seconds"])
        excess = held[era] - share
        if excess > 1e-6 and carrier["seconds"] > chosen:
            target = max(chosen, carrier["seconds"] - excess)
            start = carrier.get("start_time", 0.0)
            seconds = max(chosen, safe_end(carrier, target) - start)
            held[era] -= carrier["seconds"] - seconds
            set_duration(carrier, seconds)
        fitted.append(carrier)
    return fitted


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
                obstructed=facts.obstructed,
            )
            carrier = carrier | {"start_time": start}
            set_duration(carrier, hold)
        placed.append(carrier)
    return placed
