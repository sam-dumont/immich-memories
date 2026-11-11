"""The family tree the People page draws, read off the confirmed relationships (#2797).

Only confirmed close ties draw it: parent and child, partners, siblings. Everyone else in the
registry is left out and counted, so the page can say how many. Rows are generations: a child
sits one row under their parents, partners and siblings share a row. A family is the children
of one set of parents; a sibling whose parents nobody recorded joins their sibling's family,
drawn through the sibling, and siblings with no recorded parent at all hang from a knot of
their own. What the tree implies but nobody confirmed comes back as a suggestion, drawn
dotted and never as part of the tree (`people.kinship`).
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from immich_memories.people.account_ids import entry_ids
from immich_memories.people.companion import people_entries
from immich_memories.people.family_tree_layout import Household, place
from immich_memories.people.kinship import (
    Fact,
    Suggestion,
    close_relation,
    facts_from_document,
    suggest_relationships,
)
from immich_memories.people.owner import owner_ids

_YEAR = re.compile(r"^(\d{4})")


@dataclass(frozen=True)
class TreePerson:
    person_id: str
    name: str
    birth_year: int | None
    generation: int
    # Along the row, in person widths: partners stand 1 apart.
    x: float
    owner: bool


@dataclass(frozen=True)
class TreeChild:
    person_id: str
    # A sibling's family, not a recorded parent, puts them here: the line is drawn dashed.
    through_sibling: bool


@dataclass(frozen=True)
class TreeFamily:
    # Empty for siblings whose parents aren't in the tree.
    parents: tuple[str, ...]
    children: tuple[TreeChild, ...]


@dataclass(frozen=True)
class TreeSuggestion:
    """A close tie the tree implies and nobody confirmed: `source` is `kind` `target`."""

    source: str
    kind: str
    target: str


@dataclass(frozen=True)
class FamilyTree:
    people: tuple[TreePerson, ...]
    couples: tuple[tuple[str, str], ...]
    families: tuple[TreeFamily, ...]
    suggestions: tuple[TreeSuggestion, ...]
    # People in the registry with no confirmed parent, child, partner or sibling.
    left_out: int


@dataclass
class _Ties:
    """The confirmed close ties: each child's parents, and the partner and sibling pairs."""

    parents: dict[str, set[str]] = field(default_factory=dict)
    partners: set[tuple[str, str]] = field(default_factory=set)
    siblings: set[tuple[str, str]] = field(default_factory=set)

    @classmethod
    def read(cls, facts: list[Fact]) -> _Ties:
        ties = cls()
        for fact in facts:
            relation = close_relation(fact.kind)
            pair = (min(fact.source, fact.target), max(fact.source, fact.target))
            if relation == "parent":
                ties.parents.setdefault(fact.target, set()).add(fact.source)
            elif relation == "child":
                ties.parents.setdefault(fact.source, set()).add(fact.target)
            elif relation == "partner":
                ties.partners.add(pair)
            elif relation == "sibling":
                ties.siblings.add(pair)
        return ties

    def people(self) -> set[str]:
        found = set(self.parents).union(*self.parents.values())
        return found.union(*self.partners, *self.siblings)

    def steps(self) -> dict[str, list[tuple[str, int]]]:
        """Each person's neighbours and the row step to reach them: +1 to a child."""
        steps: dict[str, list[tuple[str, int]]] = {}
        for child, parents in self.parents.items():
            for parent in parents:
                steps.setdefault(parent, []).append((child, 1))
                steps.setdefault(child, []).append((parent, -1))
        for a, b in self.partners | self.siblings:
            steps.setdefault(a, []).append((b, 0))
            steps.setdefault(b, []).append((a, 0))
        return {person: sorted(found) for person, found in steps.items()}


def family_tree(document: dict[str, Any]) -> FamilyTree:
    """The tree a registry document draws. Same document, same tree, whatever its order."""
    entries = people_entries(document)
    facts, declined = facts_from_document(entries)
    ties = _Ties.read(facts)
    known = {entry_ids(entry)[0]: entry for entry in entries}
    drawn = ties.people() & set(known)
    owners = {pid for pid in known if pid in owner_ids(document)}
    born = {pid: _year(known[pid].get("birth_date")) for pid in drawn}
    families = _families(ties, born, known)
    generation, components = _rows(ties, drawn, owners)
    couples = tuple(sorted(ties.partners))
    x = place(
        Household(
            generation=generation,
            partners=couples,
            families=tuple((f.parents, tuple(c.person_id for c in f.children)) for f in families),
        ),
        components,
    )
    people = tuple(
        sorted(
            (
                TreePerson(
                    pid,
                    str(known[pid].get("name") or "?"),
                    born[pid],
                    generation[pid],
                    x[pid],
                    pid in owners,
                )
                for pid in drawn
            ),
            key=lambda p: (p.generation, p.x, p.person_id),
        )
    )
    return FamilyTree(
        people=people,
        couples=couples,
        families=tuple(families),
        suggestions=_dotted(suggest_relationships(facts, declined), families),
        left_out=len(known) - len(drawn),
    )


def _year(birth_date: object) -> int | None:
    found = _YEAR.match(str(birth_date or ""))
    return int(found.group(1)) if found else None


def _families(
    ties: _Ties, born: dict[str, int | None], known: dict[str, dict[str, Any]]
) -> list[TreeFamily]:
    """The children of each set of parents, eldest first, and each parentless sibling group."""
    groups: dict[tuple[tuple[str, ...], str], list[TreeChild]] = {}
    home: dict[str, tuple[tuple[str, ...], str]] = {}
    for child, parents in ties.parents.items():
        home[child] = (tuple(sorted(parents)), "")
        groups.setdefault(home[child], []).append(TreeChild(child, through_sibling=False))
    for group in _connected(ties.siblings):
        orphans = [person for person in group if person not in ties.parents]
        homes = sorted(home[person] for person in group if person in home)
        key = homes[0] if homes else ((), orphans[0])
        groups.setdefault(key, []).extend(TreeChild(p, through_sibling=True) for p in orphans)

    def eldest_first(child: TreeChild) -> tuple[int, str, str]:
        year = born[child.person_id]
        name = str(known[child.person_id].get("name") or "")
        return (year if year is not None else 10_000, name, child.person_id)

    return [
        TreeFamily(parents, tuple(sorted(children, key=eldest_first)))
        for (parents, _), children in sorted(groups.items())
    ]


def _connected(pairs: set[tuple[str, str]]) -> list[list[str]]:
    """The groups `pairs` join, each sorted, in order of their first member."""
    near: dict[str, set[str]] = {}
    for a, b in pairs:
        near.setdefault(a, set()).add(b)
        near.setdefault(b, set()).add(a)
    seen: set[str] = set()
    groups = []
    for start in sorted(near):
        if start in seen:
            continue
        group, queue = {start}, [start]
        while queue:
            for other in near[queue.pop()] - group:
                group.add(other)
                queue.append(other)
        seen |= group
        groups.append(sorted(group))
    return groups


def _rows(ties: _Ties, drawn: set[str], owners: set[str]) -> tuple[dict[str, int], list[list[str]]]:
    """Each person's row, and the connected households: the owner's first, then the largest.

    Rows are read breadth-first from one person, and the first row a person is reached on
    stays theirs, so a registry that contradicts itself still draws everybody once.
    """
    steps = ties.steps()
    generation: dict[str, int] = {}
    components = []
    for root in sorted(drawn, key=lambda p: (p not in owners, p)):
        if root in generation:
            continue
        generation[root] = 0
        members, queue = [root], deque([root])
        while queue:
            person = queue.popleft()
            for other, step in steps.get(person, []):
                if other in drawn and other not in generation:
                    generation[other] = generation[person] + step
                    members.append(other)
                    queue.append(other)
        top = min(generation[p] for p in members)
        for person in members:
            generation[person] -= top
        components.append(members)
    components.sort(key=lambda m: (not owners.intersection(m), -len(m), min(m)))
    return generation, components


def _dotted(
    suggestions: list[Suggestion], families: list[TreeFamily]
) -> tuple[TreeSuggestion, ...]:
    """The close ties the tree implies, one per pair, said from the parent's side.

    Children under one knot, or with a parent in common, are siblings on the drawing already;
    nothing to suggest there.
    """
    knot = {child.person_id: family for family in families for child in family.children}

    def drawn_as_siblings(a: str, b: str) -> bool:
        one, other = knot.get(a), knot.get(b)
        return (
            one is not None
            and other is not None
            and (one is other or bool(set(one.parents) & set(other.parents)))
        )

    found: dict[frozenset[str], TreeSuggestion] = {}
    for suggestion in suggestions:
        relation = close_relation(suggestion.kind)
        pair = frozenset((suggestion.source, suggestion.target))
        if relation is None or (
            relation == "sibling" and drawn_as_siblings(suggestion.source, suggestion.target)
        ):
            continue
        if relation == "child":
            found.setdefault(
                pair, TreeSuggestion(suggestion.target, "parent-of", suggestion.source)
            )
        else:
            found.setdefault(
                pair, TreeSuggestion(suggestion.source, suggestion.kind, suggestion.target)
            )
    return tuple(sorted(found.values(), key=lambda s: (s.source, s.kind, s.target)))
