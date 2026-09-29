"""How long a map move lasts and where the camera is on each of its frames.

Every map in a film (the trip intro and each location card) is one move: an
eased flight to the destination, then a still hold on it with its name up. The
hold is what lets a viewer read where they are, so it never shrinks to make
room; the flight takes what is left.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# A location card only exists past 30 km, so that is the shortest hop a card flies; past
# 3000 km the flight is a continent away and no longer looks longer for being longer.
_SHORT_HOP_KM = 30.0
_LONG_HOP_KM = 3000.0
# The name arrives with the camera: it fades in over the flight's last half second.
_LABEL_FADE_SECONDS = 0.5


@dataclass(frozen=True)
class MapMoveTiming:
    """The seconds a map move spends in the air and holding still on its destination."""

    min_seconds: float = 6.0
    max_seconds: float = 8.0
    hold_seconds: float = 2.0

    def seconds_for(self, distance_km: float) -> float:
        """Total seconds for a move of this length: short hops the minimum, long flights the maximum.

        Scaled on the log of the distance, since a flight from 300 to 3000 km looks as
        much longer as one from 30 to 300 km does.
        """
        span = math.log10(_LONG_HOP_KM / _SHORT_HOP_KM)
        share = math.log10(max(distance_km, _SHORT_HOP_KM) / _SHORT_HOP_KM) / span
        share = min(1.0, share)
        return self.min_seconds + share * (self.max_seconds - self.min_seconds)

    def seconds_between(self, came_from: tuple[float, float], to: tuple[float, float]) -> float:
        """Total seconds for the move between two places (see `seconds_for`)."""
        from immich_memories.analysis.trip_detection import haversine_km

        return self.seconds_for(haversine_km(*came_from, *to))

    def intro_seconds(self, home: tuple[float, float], stops: list[tuple[float, float]]) -> float:
        """Total seconds for the trip intro: the move from home to the middle of its stops."""
        middle = (
            sum(lat for lat, _ in stops) / len(stops),
            sum(lon for _, lon in stops) / len(stops),
        )
        return self.seconds_between(home, middle)

    def _frames(self, total_seconds: float, fps: float) -> tuple[int, int]:
        total = max(1, round(total_seconds * fps))
        hold = min(total, math.ceil(self.hold_seconds * fps))
        return total, total - hold

    def schedule(self, total_seconds: float, fps: float) -> list[float]:
        """The flight's progress on each frame, 0 at the start and 1 from the hold on.

        Cubic ease in and out, so the camera leaves and lands gently rather than
        snapping into a still frame.
        """
        total, moving = self._frames(total_seconds, fps)
        progress = [_ease(i / (moving - 1)) if moving > 1 else 1.0 for i in range(moving)]
        return progress + [1.0] * (total - moving)

    def label_alphas(self, total_seconds: float, fps: float) -> list[float]:
        """The destination name's opacity per frame: it fades in as the camera lands."""
        total, moving = self._frames(total_seconds, fps)
        fade = max(1, round(_LABEL_FADE_SECONDS * fps))
        start = moving - fade
        return [min(1.0, max(0.0, (i - start) / fade)) for i in range(total)]


def _ease(t: float) -> float:
    return 4.0 * t**3 if t < 0.5 else 1.0 - (-2.0 * t + 2.0) ** 3 / 2.0


def map_move_timing_of(settings: object) -> MapMoveTiming:
    """The map-move timing a settings object carries, or the defaults when it has none."""
    timing = getattr(settings, "map_move", None)
    return timing if isinstance(timing, MapMoveTiming) else MapMoveTiming()
