"""The household the family tree is drawn from, in the browser test and the docs screenshot.

The fixture library's made-up cast, under the ids its fake Immich serves faces for. Three
generations: Pat and Lou, their children Robin (the owner) and Sasha, Robin's partner Charlie
and Charlie's sibling Mo (their parents aren't in the tree), and the grandchildren. Remy's
second parent is only implied, so the tree offers it as a dotted line. Jo and Alex are only
friends: left out, and counted.
"""

from __future__ import annotations

from typing import Any

from immich_memories.people.relationships import reciprocal_kind

OWNER = "Robin"
BORN: dict[str, str | None] = {
    "Pat": "1955-04-20",
    "Lou": "1957-09-09",
    "Robin": "1987-03-14",
    "Sasha": "1989-12-12",
    "Charlie": "1986-11-02",
    "Mo": None,
    "Kit": "2020-07-05",
    "Remy": "2024-02-10",
    "Nico": "2009-05-30",
    "Jo": "2019-10-01",
    "Alex": "2020-01-15",
}
RELATIONSHIPS: tuple[tuple[str, str, str], ...] = (
    ("Pat", "partner-of", "Lou"),
    ("Robin", "child-of", "Pat"),
    ("Robin", "child-of", "Lou"),
    ("Sasha", "child-of", "Pat"),
    ("Sasha", "child-of", "Lou"),
    ("Charlie", "partner-of", "Robin"),
    ("Charlie", "sibling-of", "Mo"),
    ("Kit", "child-of", "Robin"),
    ("Kit", "child-of", "Charlie"),
    ("Remy", "child-of", "Robin"),
    ("Nico", "child-of", "Sasha"),
    ("Jo", "friend-of", "Kit"),
    ("Alex", "friend-of", "Kit"),
)


def person_id(name: str) -> str:
    """The id the fake Immich gives a cast member, and serves their face under."""
    return f"person-{name.lower()}"


def household() -> dict[str, Any]:
    """The registry as `people import` takes it, both directions of every relationship."""
    links: dict[str, list[dict[str, str]]] = {name: [] for name in BORN}
    for name, kind, other in RELATIONSHIPS:
        for who, what, whom in ((name, kind, other), (other, reciprocal_kind(kind), name)):
            links[who].append({"kind": what, "with": person_id(whom), "decision": "confirmed"})
    return {
        "version": 1,
        "owner": {"person_id": person_id(OWNER), "name": OWNER, "identified": "confirmed"},
        "people": [
            {
                "ids": [person_id(name)],
                "name": name,
                "birth_date": born,
                "inferred": {"tier": "inner", "counts_reliable": True, "evidence": {"count": 40}},
                "confirmed": {"role": None, "links": links[name], "notes": None},
            }
            for name, born in BORN.items()
        ],
    }
