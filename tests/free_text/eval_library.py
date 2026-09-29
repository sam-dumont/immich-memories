"""The synthetic household every recorded prompt is translated against.

Invented from end to end: placeholder people, a home at made-up coordinates, invented place
names, and captions written for the prompt shapes of the evaluation set. Each group of
pictures is a set of days of its own, hours from any other group, so no episode joins two.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from immich_memories.free_text.library import LibraryPerson, LibraryPicture, LibraryView

HOME = (10.0, 20.0)
AWAY = (40.0, 60.0)
SHARPNESS_LINE = 0.3

OWNER = LibraryPerson("p-owner", "Ada Placeholder", None, date(1990, 6, 15))
PARTNER = LibraryPerson("p-partner", "Bo Placeholder", "partner", date(1991, 2, 1))
CHILD = LibraryPerson("p-child", "Cy Placeholder", "son", date(2018, 4, 2))
FRIEND = LibraryPerson("p-friend", "Di Sample", "friend", None)
PEOPLE = {person.person_id: person for person in (OWNER, PARTNER, CHILD, FRIEND)}

# name: (caption, how many, first day, days apart, fields)
GROUPS: dict[str, tuple[str, int, str, int, dict[str, Any]]] = {
    "car": ("A red car parked on a street", 14, "2016-03-05", 90, {}),
    "bread": ("A bread on a wooden board", 14, "2016-04-07", 120, {}),
    "park": ("Two children playing on a swing in a park", 14, "2019-05-11", 60, {}),
    "bench": ("An empty bench in a park", 4, "2019-06-20", 30, {}),
    "eyes": ("A baby with closed eyes lying on a blanket", 14, "2018-05-01", 70, {}),
    "race": ("Runners crossing the finish line of a race", 14, "2016-09-18", 100, {}),
    "cat": ("A black cat sleeping on a sofa", 14, "2016-01-10", 150, {}),
    "screen": (
        "A screenshot of a phone screen showing a map",
        6,
        "2021-02-02",
        40,
        {"picture_kind": "screenshot_from_computer"},
    ),
    "trip": (
        "A landscape of palm trees and the sea",
        14,
        "2022-07-01",
        1,
        {"city": "Northvale", "country": "Examplia", "latitude": AWAY[0], "longitude": AWAY[1]},
    ),
    "blur": ("A dog running on grass", 14, "2020-08-08", 20, {"sharpness": 0.1}),
    "sharp": ("A dog sitting on grass", 14, "2020-08-09", 20, {"sharpness": 0.8}),
    "family": (
        "A child and a woman smiling at a table",
        40,
        "2018-06-03",
        30,
        {"people": frozenset({"p-child", "p-partner"})},
    ),
    "friend": ("A man waving", 5, "2019-01-04", 30, {"people": frozenset({"p-friend"})}),
    # Home, photographed most days of the trip's year, so that year's home is not the trip.
    "garden": ("A garden with flowers", 30, "2022-01-03", 7, {}),
    "rides": ("A group of cyclists riding on a road", 14, "2017-04-02", 45, {}),
    "party": (
        "Friends dancing at a party",
        14,
        "2008-02-11",
        150,
        {"people": frozenset({"p-owner", "p-friend"})},
    ),
    "guests": (
        "Guests dancing at a wedding",
        6,
        "2017-09-16",
        0,
        {"people": frozenset({"p-partner"})},
    ),
}


def _group(name: str, hour: int) -> list[LibraryPicture]:
    caption, count, first, apart, fields = GROUPS[name]
    start = datetime.fromisoformat(first).replace(hour=hour, tzinfo=UTC)
    fields = {"city": "Homeburg", "country": "Homeland"} | fields
    if "latitude" not in fields:
        fields |= {"latitude": HOME[0], "longitude": HOME[1]}
    return [
        LibraryPicture(
            f"{name}-{n}",
            start + timedelta(days=apart * n, minutes=5 * n if apart == 0 else 0),
            "photo",
            caption=caption,
            **fields,
        )
        for n in range(count)
    ]


def household_library() -> LibraryView:
    """Every group, in time order, with the people file and the engine's sharpness line."""
    # Each group its own hour of the day, three hours apart: no episode (90 min) joins two.
    pictures = [
        picture for n, name in enumerate(GROUPS) for picture in _group(name, hour=(6 + 3 * n) % 24)
    ]
    return LibraryView(
        pictures=tuple(sorted(pictures, key=lambda picture: picture.taken_at)),
        people=PEOPLE,
        sharpness_line=SHARPNESS_LINE,
        owner_id=OWNER.person_id,
    )


def group(name: str) -> set[str]:
    """The asset ids of one group, for a fixture's expected pool."""
    return {f"{name}-{n}" for n in range(GROUPS[name][1])}
