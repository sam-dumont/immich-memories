"""The household the family tree is drawn from, in the browser test and the docs screenshot.

The fixture library's made-up cast, under the ids its fake Immich serves faces for. Three
generations: Pat and Lou, their children Robin (the owner) and Sasha, Robin's partner Charlie
and Charlie's sibling Mo (their parents aren't in the tree), and the grandchildren. Remy's
second parent is only implied, so the tree offers it as a dotted line. Jo and Alex are only
friends: left out, and counted.

`two_families()` is a bigger household, four generations, where a couple joins two families:
each family's children must hang from their own line.
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


# A great-grandmother over Pat and Lou, whose children are Sasha, Sam (the owner) and Robin;
# Quinn and Dale, whose children are Kit (Sam's partner) and Mia; Dale's sister Ari and her
# partner. Robin and Mia married people whose parents aren't in the tree. Under them, Sasha's
# two, Sam and Kit's one and Robin and Jo's four.
TWO_FAMILIES: tuple[tuple[str, str, str], ...] = (
    ("Gran", "parent-of", "Pat"),
    ("Pat", "partner-of", "Lou"),
    ("Quinn", "partner-of", "Dale"),
    ("Dale", "sibling-of", "Ari"),
    ("Ari", "partner-of", "Bo"),
    *(
        (child, "child-of", parent)
        for child in ("Sasha", "Sam", "Robin")
        for parent in ("Pat", "Lou")
    ),
    *((child, "child-of", parent) for child in ("Kit", "Mia") for parent in ("Quinn", "Dale")),
    ("Sam", "partner-of", "Kit"),
    ("Robin", "partner-of", "Jo"),
    ("Mia", "partner-of", "Max"),
    *((child, "child-of", "Sasha") for child in ("Ada", "Ben")),
    *((child, "child-of", parent) for child in ("Cy",) for parent in ("Sam", "Kit")),
    *(
        (child, "child-of", parent)
        for child in ("Dee", "Eve", "Fay", "Gus")
        for parent in ("Robin", "Jo")
    ),
)
TWO_FAMILIES_BORN: dict[str, str | None] = {
    "Sasha": "1980-01-01",
    "Sam": "1983-01-01",
    "Kit": "1984-01-01",
    "Robin": "1986-01-01",
    "Mia": "1988-01-01",
}


def person_id(name: str) -> str:
    """The id the fake Immich gives a cast member, and serves their face under."""
    return f"person-{name.lower()}"


def two_families() -> dict[str, Any]:
    """The four-generation household where a couple joins two families, Sam the owner."""
    names = dict.fromkeys(n for r in TWO_FAMILIES for n in (r[0], r[2]))
    return household(TWO_FAMILIES, {n: TWO_FAMILIES_BORN.get(n) for n in names}, "Sam")


def household(
    relationships: tuple[tuple[str, str, str], ...] = RELATIONSHIPS,
    born: dict[str, str | None] = BORN,
    owner: str = OWNER,
) -> dict[str, Any]:
    """The registry as `people import` takes it, both directions of every relationship."""
    links: dict[str, list[dict[str, str]]] = {name: [] for name in born}
    for name, kind, other in relationships:
        for who, what, whom in ((name, kind, other), (other, reciprocal_kind(kind), name)):
            links[who].append({"kind": what, "with": person_id(whom), "decision": "confirmed"})
    return {
        "version": 1,
        "owner": {"person_id": person_id(owner), "name": owner, "identified": "confirmed"},
        "people": [
            {
                "ids": [person_id(name)],
                "name": name,
                "birth_date": date,
                "inferred": {"tier": "inner", "counts_reliable": True, "evidence": {"count": 40}},
                "confirmed": {"role": None, "links": links[name], "notes": None},
            }
            for name, date in born.items()
        ],
    }
