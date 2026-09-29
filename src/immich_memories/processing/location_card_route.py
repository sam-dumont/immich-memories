"""When a trip film gets a location card, and the place each card flies from.

One rule for the divider planner, which inserts the cards, and the timeline budget,
which reserves their regular cost: a card the budget did not count would be cut by
the divider cap, and one it counted but the planner never inserts would cost content.

A hop of more than 30 km always gets a card. A walking or cycling trip moves from
village to village well under that, so a change of geocoded town also gets one: at
most one a day, never the town the last card named, never a town at home. Each card
flies from the place the previous card named, the first one from the trip's first
located picture.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from immich_memories.analysis.trip_detection import AWAY_FROM_HOME_KM, haversine_km

# A hop this long is a new place whatever the geocoder calls it.
_LONG_HOP_KM = 30.0

Point = tuple[float, float]


@dataclass(frozen=True)
class RouteStop:
    """One picture as the card rule sees it: where, what town, which day."""

    lat: float | None
    lon: float | None
    name: str | None
    day: date | None


@dataclass(frozen=True)
class CardMove:
    """A card before a stop: the place it flies from and why it is there."""

    came_from: Point
    reason: str


class _RouteSoFar:
    """Where a trip film has been, as far as its location cards are concerned."""

    def __init__(self) -> None:
        self.cards = 0
        self.last_card_point: Point | None = None
        self._point: Point | None = None
        self._town: str | None = None
        self._last_card: str | None = None
        self._carded_days: set[date] = set()

    def card_reason(self, stop: RouteStop, home: Point | None) -> str | None:
        if stop.lat is None or stop.lon is None or self._point is None:
            return None
        hop = haversine_km(*self._point, stop.lat, stop.lon)
        if hop > _LONG_HOP_KM:
            return f"{hop:.0f} km"
        if (
            stop.day is None
            or stop.day in self._carded_days
            or not stop.name
            or stop.name in (self._town, self._last_card)
        ):
            return None
        if home and haversine_km(*home, stop.lat, stop.lon) <= AWAY_FROM_HOME_KM:
            return None
        return "new town"

    def carded(self, stop: RouteStop, here: Point) -> None:
        self.cards += 1
        self._last_card = stop.name
        self.last_card_point = here
        if stop.day is not None:
            self._carded_days.add(stop.day)

    def passed(self, stop: RouteStop) -> None:
        if stop.lat is not None and stop.lon is not None:
            self._point = (stop.lat, stop.lon)
            self._town = stop.name
            self.last_card_point = self.last_card_point or self._point


def location_card_moves(
    stops: list[RouteStop], limit: int | None, home: Point | None
) -> list[CardMove | None]:
    """For each stop, the card that goes before it, or None; at most `limit` cards."""
    route = _RouteSoFar()
    moves: list[CardMove | None] = []
    for stop in stops:
        move = None
        reason = route.card_reason(stop, home)
        if reason and stop.name and (limit is None or route.cards < limit):
            assert stop.lat is not None and stop.lon is not None  # noqa: S101
            assert route.last_card_point is not None  # noqa: S101
            move = CardMove(route.last_card_point, reason)
            route.carded(stop, (stop.lat, stop.lon))
        route.passed(stop)
        moves.append(move)
    return moves
