"""The relationships a family tree already implies, offered as suggestions (#2795).

A grandparent is a parent's parent; nobody should have to type that in. The rules here
read only what somebody confirmed and return suggestions with the chain they follow, so
the editor can say why. A suggestion is never a fact: the film logic reads the confirmed
registry and never sees one until somebody accepts it. Partners count for in-laws even
when they are not married, and two children of one parent count as siblings even when
they are half-siblings; both are reasons these stay suggestions.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from immich_memories.people.relationships import DETECTED_KINDS, reciprocal_kind

_PARENT = frozenset({"parent-of", "mother-of", "father-of"})
_CHILD = frozenset({"child-of", "son-of", "daughter-of"})
_SIBLING = frozenset({"sibling-of", "sister-of", "brother-of", "twin-of"})
_PARTNER = frozenset({"partner-of", "spouse-of"})
# A pair already tied this closely is never offered a weaker derived tie on top.
_CLOSE = _PARENT | _CHILD | _SIBLING | _PARTNER

# The recorded kinds that already say what a suggested kind would.
_ANSWERED_BY = {
    "sibling-of": _SIBLING,
    "grandparent-of": frozenset({"grandparent-of"}),
    "grandchild-of": frozenset({"grandchild-of"}),
    "aunt-or-uncle-of": frozenset({"aunt-or-uncle-of", "aunt-of", "uncle-of"}),
    "nibling-of": frozenset({"nibling-of"}),
    "cousin-of": frozenset({"cousin-of"}),
    "parent-in-law-of": frozenset({"parent-in-law-of"}),
    "child-in-law-of": frozenset({"child-in-law-of"}),
    "sibling-in-law-of": frozenset({"sibling-in-law-of"}),
}


@dataclass(frozen=True)
class Fact:
    """One recorded relationship: `source` is `kind` `target` ("bob", "parent-of", "riley")."""

    source: str
    kind: str
    target: str


@dataclass(frozen=True)
class Hop:
    """One step of the chain: the source is the `relation` (parent, child, sibling, partner)
    of `person`."""

    relation: str
    person: str


@dataclass(frozen=True)
class Suggestion:
    """A relationship the tree implies, and the chain of recorded ones it follows."""

    source: str
    kind: str
    target: str
    reverse_kind: str
    hops: tuple[Hop, ...]


class _Tree:
    """The recorded facts, indexed by the four relations the rules walk."""

    def __init__(self, facts: Iterable[Fact], declined: Iterable[Fact]):
        self.parents: dict[str, set[str]] = defaultdict(set)
        self.children: dict[str, set[str]] = defaultdict(set)
        self.siblings: dict[str, set[str]] = defaultdict(set)
        self.partners: dict[str, set[str]] = defaultdict(set)
        self.kinds = _pair_kinds(facts, self._index)
        self.declined = _pair_kinds(declined, lambda _fact: None)

    def _index(self, fact: Fact) -> None:
        a, b, kind = fact.source, fact.target, fact.kind
        if kind in _PARENT:
            self.children[a].add(b)
            self.parents[b].add(a)
        elif kind in _CHILD:
            self.parents[a].add(b)
            self.children[b].add(a)
        elif kind in _SIBLING:
            self.siblings[a].add(b)
            self.siblings[b].add(a)
        elif kind in _PARTNER:
            self.partners[a].add(b)
            self.partners[b].add(a)

    def sibling_hops(self, person: str) -> dict[str, tuple[Hop, ...]]:
        """Each sibling and how the tree knows: said outright, or through a shared parent."""
        found: dict[str, tuple[Hop, ...]] = {s: (Hop("sibling", s),) for s in self.siblings[person]}
        for parent in sorted(self.parents[person]):
            for sibling in sorted(self.children[parent]):
                found.setdefault(sibling, (Hop("child", parent), Hop("parent", sibling)))
        found.pop(person, None)
        return found

    def answered(self, source: str, kind: str, target: str) -> bool:
        recorded = self.kinds.get((source, target), set())
        said_no = self.declined.get((source, target), set())
        return bool(
            recorded & (_ANSWERED_BY[kind] | _CLOSE)
            or said_no & (_ANSWERED_BY[kind] | DETECTED_KINDS)
        )


def suggest_relationships(facts: Iterable[Fact], declined: Iterable[Fact] = ()) -> list[Suggestion]:
    """Every relationship `facts` imply that nobody recorded or declined, sorted.

    `declined` holds the answers "no" (a rejected suggestion, or "not related" to a
    detected pair); either side's answer counts for both.
    """
    tree = _Tree(facts, declined)
    found: dict[tuple[str, str, str], Suggestion] = {}
    people = set(tree.parents) | set(tree.children) | set(tree.siblings) | set(tree.partners)
    for person in sorted(people):
        for kind, target, hops in _implied(tree, person):
            key = (person, kind, target)
            if target == person or key in found or tree.answered(person, kind, target):
                continue
            if kind != "sibling-of" and target in tree.sibling_hops(person):
                continue
            found[key] = Suggestion(person, kind, target, reciprocal_kind(kind), hops)
    return [found[key] for key in sorted(found)]


_Implied = Iterable[tuple[str, str, tuple[Hop, ...]]]


def _implied(tree: _Tree, x: str) -> _Implied:
    """(kind, target, chain) for every rule that reaches someone from `x`."""
    yield from _through_siblings(tree, x)
    yield from _through_children(tree, x)
    yield from _through_parents(tree, x)
    yield from _through_partners(tree, x)


def _through_siblings(tree: _Tree, x: str) -> _Implied:
    for sibling, hops in sorted(tree.sibling_hops(x).items()):
        if sibling not in tree.siblings[x]:
            yield "sibling-of", sibling, hops
        for child in sorted(tree.children[sibling]):
            yield "aunt-or-uncle-of", child, (Hop("sibling", sibling), Hop("parent", child))
        for partner in sorted(tree.partners[sibling]):
            yield "sibling-in-law-of", partner, (Hop("sibling", sibling), Hop("partner", partner))


def _through_children(tree: _Tree, x: str) -> _Implied:
    for child in sorted(tree.children[x]):
        for grandchild in sorted(tree.children[child]):
            yield "grandparent-of", grandchild, (Hop("parent", child), Hop("parent", grandchild))
        for partner in sorted(tree.partners[child]):
            yield "parent-in-law-of", partner, (Hop("parent", child), Hop("partner", partner))


def _through_parents(tree: _Tree, x: str) -> _Implied:
    for parent in sorted(tree.parents[x]):
        for grandparent in sorted(tree.parents[parent]):
            yield "grandchild-of", grandparent, (Hop("child", parent), Hop("child", grandparent))
        for aunt in sorted(tree.sibling_hops(parent)):
            via_aunt = (Hop("child", parent), Hop("sibling", aunt))
            yield "nibling-of", aunt, via_aunt
            for cousin in sorted(tree.children[aunt]):
                yield "cousin-of", cousin, (*via_aunt, Hop("parent", cousin))


def _through_partners(tree: _Tree, x: str) -> _Implied:
    for partner in sorted(tree.partners[x]):
        for in_law in sorted(tree.parents[partner]):
            yield "child-in-law-of", in_law, (Hop("partner", partner), Hop("child", in_law))
        for sibling in sorted(tree.sibling_hops(partner)):
            yield "sibling-in-law-of", sibling, (Hop("partner", partner), Hop("sibling", sibling))


def _pair_kinds(
    facts: Iterable[Fact], each: Callable[[Fact], None]
) -> dict[tuple[str, str], set[str]]:
    """Every kind recorded between two people, from both sides, through the reciprocal."""
    kinds: dict[tuple[str, str], set[str]] = defaultdict(set)
    for fact in facts:
        each(fact)
        kinds[(fact.source, fact.target)].add(fact.kind)
        kinds[(fact.target, fact.source)].add(reciprocal_kind(fact.kind))
    return kinds
