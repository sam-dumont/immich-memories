"""The relationships a family tree already implies, offered as suggestions (#2795).

A grandparent is a parent's parent; nobody should have to type that in. The rules here
read only what somebody confirmed and return suggestions with the chain they follow, so
the editor can say why. A suggestion is never a fact: the film logic reads the confirmed
registry and never sees one until somebody accepts it.

The tree's own implications count before anything else is read off it: two children of
one parent are siblings, a sibling's sibling and a sibling's parent are one's own, and a
parent's partner is the other parent. Those close ties are suggested too, and the rules
for grandparents, cousins, aunts, uncles and in-laws then follow them, so a chain of
several steps still arrives. Partners count for in-laws even when they are not married,
a parent's partner may be a step-parent, and two children of one parent may be
half-siblings; these are the reasons every one of them stays a suggestion. An answered
"no" ends a chain there: a declined tie is never a step of another one.
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

# Each close relation, the kinds that record it, and the one it reads as from the other side.
_RELATION_KINDS = {"parent": _PARENT, "child": _CHILD, "sibling": _SIBLING, "partner": _PARTNER}
_INVERSE = {"parent": "child", "child": "parent", "sibling": "sibling", "partner": "partner"}
# The close ties the tree implies, suggested under these kinds. Partners are never implied.
_SUGGESTED_AS = {"parent": "parent-of", "child": "child-of", "sibling": "sibling-of"}

# The recorded kinds that already say what a suggested kind would.
_ANSWERED_BY = {
    "parent-of": _PARENT,
    "child-of": _CHILD,
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

# How the close ties close over themselves: (relation implied, the relations walked).
_CLOSURE = (
    ("sibling", ("child", "parent")),  # two children of one parent
    ("sibling", ("sibling", "sibling")),  # a sibling's sibling
    ("child", ("sibling", "child")),  # a sibling's parent
    ("parent", ("partner", "parent")),  # a partner's child
)

# The wider kinds, read off the closed tree: (kind suggested, the relations walked).
_RULES = (
    ("grandparent-of", ("parent", "parent")),
    ("grandchild-of", ("child", "child")),
    ("aunt-or-uncle-of", ("sibling", "parent")),
    ("aunt-or-uncle-of", ("partner", "sibling", "parent")),
    ("nibling-of", ("child", "sibling")),
    ("nibling-of", ("child", "sibling", "partner")),
    ("cousin-of", ("child", "sibling", "parent")),
    ("parent-in-law-of", ("parent", "partner")),
    ("child-in-law-of", ("partner", "child")),
    ("sibling-in-law-of", ("sibling", "partner")),
    ("sibling-in-law-of", ("partner", "sibling")),
)

# Every round can only add a tie or shorten a chain, so this is a guard, not a limit
# any real family reaches.
_MAX_ROUNDS = 32


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


Chain = tuple[Hop, ...]


class _Tree:
    """The close ties, recorded and implied, each with the shortest chain of recorded ones."""

    def __init__(self, facts: Iterable[Fact], declined: Iterable[Fact]):
        # (person, relation) -> {other: chain}: person is the relation of other.
        self.ties: dict[tuple[str, str], dict[str, Chain]] = defaultdict(dict)
        self.kinds = _pair_kinds(facts, self._record)
        self.declined = _pair_kinds(declined, lambda _fact: None)
        self._close()

    @property
    def people(self) -> list[str]:
        return sorted({person for person, _relation in self.ties})

    def of(self, person: str, relation: str) -> dict[str, Chain]:
        return self.ties.get((person, relation), {})

    def tied(self, a: str, b: str) -> bool:
        """Whether two people already share a close tie, recorded or implied."""
        return any(b in self.of(a, relation) for relation in _RELATION_KINDS)

    def walk(self, person: str, relations: tuple[str, ...]) -> Iterable[tuple[str, Chain]]:
        """Everyone reached by following `relations` in turn, never through anyone twice."""
        reached: list[tuple[str, Chain]] = [(person, ())]
        for relation in relations:
            reached = [
                (other, chain + step)
                for at, chain in reached
                for other, step in sorted(self.of(at, relation).items())
                if _simple(person, chain + step)
            ]
        return reached

    def answered(self, source: str, kind: str, target: str) -> bool:
        recorded = self.kinds.get((source, target), set())
        said_no = self.declined.get((source, target), set())
        return bool(
            recorded & (_ANSWERED_BY[kind] | _CLOSE)
            or said_no & (_ANSWERED_BY[kind] | DETECTED_KINDS)
        )

    def _record(self, fact: Fact) -> None:
        relation = next((r for r, kinds in _RELATION_KINDS.items() if fact.kind in kinds), None)
        if relation is not None and fact.source != fact.target:
            self._tie(fact.source, relation, fact.target, (Hop(relation, fact.target),))

    def _tie(self, a: str, relation: str, b: str, chain: Chain) -> None:
        self.ties[(a, relation)][b] = chain
        self.ties[(b, _INVERSE[relation])][a] = _reversed(a, chain)

    def _close(self) -> None:
        for _round in range(_MAX_ROUNDS):
            implied = [
                (person, relation, other, chain)
                for person in self.people
                for relation, path in _CLOSURE
                for other, chain in self.walk(person, path)
            ]
            changed = False
            for person, relation, other, chain in implied:
                changed |= self._imply(person, relation, other, chain)
            if not changed:
                return

    def _imply(self, a: str, relation: str, b: str, chain: Chain) -> bool:
        """Keep an implied tie unless an answer rules it out; True when the tree changed."""
        known = self.of(a, relation).get(b)
        if a == b or (known is not None and len(known) <= len(chain)):
            return False
        if known is None and (self._contradicts(a, b) or self._declined(a, relation, b)):
            return False
        self._tie(a, relation, b, chain)
        return True

    def _contradicts(self, a: str, b: str) -> bool:
        return self.tied(a, b) or bool(self.kinds.get((a, b), set()) & _CLOSE)

    def _declined(self, a: str, relation: str, b: str) -> bool:
        said_no = self.declined.get((a, b), set())
        return bool(said_no & (_RELATION_KINDS[relation] | DETECTED_KINDS))


def suggest_relationships(facts: Iterable[Fact], declined: Iterable[Fact] = ()) -> list[Suggestion]:
    """Every relationship `facts` imply that nobody recorded or declined, sorted.

    `declined` holds the answers "no" (a rejected suggestion, or "not related" to a
    detected pair); either side's answer counts for both. Where the tree implies one
    relationship several ways, the shortest chain is the one shown.
    """
    tree = _Tree(facts, declined)
    found: dict[tuple[str, str, str], Suggestion] = {}
    for person in tree.people:
        for kind, target, hops in _implied(tree, person):
            key = (person, kind, target)
            if target == person or tree.answered(person, kind, target):
                continue
            if kind not in _SUGGESTED_AS.values() and tree.tied(person, target):
                continue
            known = found.get(key)
            if known is None or _shorter(hops, known.hops):
                found[key] = Suggestion(person, kind, target, reciprocal_kind(kind), hops)
    return [found[key] for key in sorted(found)]


def _implied(tree: _Tree, person: str) -> Iterable[tuple[str, str, Chain]]:
    """(kind, target, chain) for every close tie and every rule that reaches someone."""
    for relation, kind in _SUGGESTED_AS.items():
        for other, chain in sorted(tree.of(person, relation).items()):
            yield kind, other, chain
    for kind, path in _RULES:
        for other, chain in tree.walk(person, path):
            yield kind, other, chain


def _simple(start: str, chain: Chain) -> bool:
    """A chain that passes through nobody twice, its start included."""
    people = [start, *(hop.person for hop in chain)]
    return len(people) == len(set(people))


def _reversed(start: str, chain: Chain) -> Chain:
    """The same chain read from its other end."""
    people = [start, *(hop.person for hop in chain)]
    return tuple(
        Hop(_INVERSE[hop.relation], people[index])
        for index, hop in reversed(list(enumerate(chain)))
    )


def _shorter(chain: Chain, than: Chain) -> bool:
    def order(c: Chain) -> tuple[int, list[tuple[str, str]]]:
        return len(c), [(hop.relation, hop.person) for hop in c]

    return order(chain) < order(than)


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
