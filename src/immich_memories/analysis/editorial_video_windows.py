"""Which part of a kept video plays (#1949).

The editor chooses which videos make the film; this chooses where inside each one the hold
sits. Until the story-first route every clip was scored on its own segments; the route kept
the clip choice and lost that step, so every video played from its first frame and a finish
line showed the empty road before the riders.

The window is read off how much each half second of the clip changes, which the MP4 index
already says through the size of every predicted frame, and off the speech the cut
measured when it has it. Nothing is decoded: on the June finish-line clips (4K60, keyframes
four seconds apart) optical flow over sixteen probes read the whole 155 MB file in 3.2 s,
where the index read 64 KB in 2 ms and placed the window on the bunch all the same. The
opening stays unless another window clearly holds more: a clip that is busy or quiet
throughout gives no reason to move.
"""

from __future__ import annotations

import logging
import struct
from collections.abc import Callable, Sequence

import httpx

from immich_memories.analysis.editorial_structure_budget import MIN_CARRIER_SECONDS
from immich_memories.api.access_clients import AccountReadFailed
from immich_memories.processing.playback_keyframes import frame_activity
from immich_memories.speech.cuts import set_duration

logger = logging.getLogger(__name__)

Activity = Sequence[tuple[float, float]]

# The step a window start moves in; half the activity bin, coarser than a frame.
STEP_SECONDS = 0.25
# A later window must beat the opening by this much: encoder noise alone never moves a cut.
CLEAR_MARGIN = 1.25
# Past the minimum hold a clip may be shaved from its end, so action there counts for less.
SHAVABLE_WEIGHT = 0.5


def _score(start: float, hold: float, probes, peak: float, speech) -> float:
    sure_end, end = start + min(hold, MIN_CARRIER_SECONDS), start + hold
    motion = sum(
        (1.0 if t < sure_end else SHAVABLE_WEIGHT) * m / peak for t, m in probes if start <= t < end
    )
    spoken = sum(max(0.0, min(end, right) - max(start, left)) for left, right in speech)
    return motion + spoken


def choose_window(
    probes: Sequence[tuple[float, float]],
    *,
    duration: float,
    hold: float,
    speech: Sequence[tuple[float, float]] = (),
) -> float:
    """The start, in source seconds, of the ``hold`` that shows the most of this clip.

    ``probes`` are (second, activity) readings; ``speech`` the measured utterances. A clip no
    longer than its hold, or one with nothing that stands out, keeps its opening.
    """
    peak = max((m for _, m in probes), default=0.0)
    if duration <= hold or (peak <= 0 and not speech):
        return 0.0
    peak = peak or 1.0
    starts = [i * STEP_SECONDS for i in range(int((duration - hold) / STEP_SECONDS) + 1)]
    opening = _score(0.0, hold, probes, peak, speech)
    best = max(starts, key=lambda s: (_score(s, hold, probes, peak, speech), -s))
    if _score(best, hold, probes, peak, speech) <= opening * CLEAR_MARGIN + 1e-9:
        return 0.0
    return best


def place_windows(
    carriers: list[dict], activity_for: Callable[[str], Activity | None]
) -> list[dict]:
    """Start each kept video where its hold shows the most; every other carrier passes through.

    A video that already has a start (an owner's edit), plays whole, or could not be probed
    keeps its interval.
    """
    placed = []
    for carrier in carriers:
        raw = float(carrier.get("raw_seconds") or 0.0)
        movable = carrier["kind"] == "video" and "start_time" not in carrier
        probes = activity_for(carrier["asset_id"]) if movable and raw > carrier["seconds"] else None
        if probes:
            hold = carrier["seconds"]
            speech = carrier.get("speech_regions") or ()
            carrier = carrier | {
                "start_time": choose_window(probes, duration=raw, hold=hold, speech=speech)
            }
            set_duration(carrier, hold)
        placed.append(carrier)
    return placed


class PlaybackActivity:
    """A kept video's activity, read off its playback index by byte range.

    ``read(asset_id, start, length)`` answers a byte range with the playback's full size. A
    playback that cannot be indexed answers None and keeps its opening.
    """

    def __init__(self, read: Callable[[str, int, int], tuple[bytes, int]]) -> None:
        self._read = read

    def __call__(self, asset_id: str) -> list[tuple[float, float]] | None:
        try:
            return list(
                frame_activity(lambda start, length: self._read(asset_id, start, length)).bins
            )
        except AccountReadFailed:
            raise
        except (httpx.HTTPError, OSError, ValueError, struct.error) as error:
            # WHY: the window refines a valid cut; a clip whose index cannot be read plays
            # its opening, as every clip did before.
            logger.warning("Could not read %s for its window: %s", asset_id, error)
            return None
