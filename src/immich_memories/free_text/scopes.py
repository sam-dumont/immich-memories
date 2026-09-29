"""Where a picture was taken, against the place a request linked: a home, near it, or away.

Distances are from the home of the picture's own time (a library that spans a move has
several), and a picture without GPS is no evidence of elsewhere: it stays unless the subject
is one particular place, which only a GPS fix can prove.
"""

from __future__ import annotations

from collections.abc import Sequence

from immich_memories.analysis.editorial_home_radius import HOME_RADIUS_KM
from immich_memories.analysis.trip_detection import haversine_km
from immich_memories.free_text.facts import TripRules, home_trips
from immich_memories.free_text.homes import Home
from immich_memories.free_text.library import LibraryPicture
from immich_memories.free_text.linking import Reason, WhereLink

# At a home is on its plot: 500 m took in the neighbours' houses.
AT_HOME_KM = 0.15

_SCOPES = {
    "home": ("at that home", AT_HOME_KM),
    "home_at_time": ("at the home of the picture's time", AT_HOME_KM),
    "near_home": ("near the home of the picture's time", HOME_RADIUS_KM),
}


def in_place(
    where: WhereLink,
    pictures: Sequence[LibraryPicture],
    homes: Sequence[Home],
    rules: TripRules,
    *,
    require_gps: bool = False,
) -> tuple[list[LibraryPicture], Reason] | None:
    """The pictures taken where the request says, and why; None when it says anywhere."""
    if where.scope == "anywhere":
        return None
    if not homes:
        return [], Reason(where.scope, "no home known", "where the owner lives cannot be told")
    if where.scope == "trips":
        ids = {
            asset_id
            for _, trip in home_trips(pictures, homes, rules)
            for asset_id in trip.asset_ids
        }
        kept = [picture for picture in pictures if picture.asset_id in ids]
        rule = "the product's trips, detected from the home of each trip's time"
        return kept, Reason(where.scope, rule, "away from home")
    said, radius = _SCOPES[where.scope]
    chosen = (where.home,) if where.scope == "home" and where.home else None
    kept = [
        picture
        for picture in pictures
        if _within(picture, chosen or _home_then(picture, homes), radius, require_gps)
    ]
    rule = f"within {radius * 1000:.0f} m" if radius < 1 else f"within {radius:.0f} km"
    if require_gps:
        rule += "; the subject is one particular place, so a picture must carry GPS"
    else:
        rule += "; a picture without GPS stays"
    return kept, Reason(where.scope, rule, said)


def _home_then(picture: LibraryPicture, homes: Sequence[Home]) -> tuple[Home, ...]:
    day = picture.taken_at.date()
    return tuple(home for home in homes if home.held_on(day))[-1:]


def _within(
    picture: LibraryPicture, homes: Sequence[Home], radius: float, require_gps: bool
) -> bool:
    if picture.latitude is None or picture.longitude is None:
        return not require_gps
    return any(
        haversine_km(home.latitude, home.longitude, picture.latitude, picture.longitude) <= radius
        for home in homes
    )
