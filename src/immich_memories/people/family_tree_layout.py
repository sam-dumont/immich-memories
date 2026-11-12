"""Where each person of the family tree sits along their row (#2797).

Rows are generations, decided before this runs. Partners sit side by side as one block. A
family's children spread under their parents' knot, and a married child sits on the side of
the family that faces their partner's, so the two families' lines don't cross. Placement is a
few sweeps down and up the rows: going down, each block asks for the place under its parents;
going up, each block asks for the place over its children. The row then keeps its blocks
apart while moving them as little as it can, which is an isotonic regression solved by pooling
adjacent violators. Same input, same places: nothing here is random or depends on dict order.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

# Partners stand one unit apart; blocks and the children of a family a little further.
PARTNER_STEP = 1.0
BLOCK_GAP = 1.25
COMPONENT_GAP = 2.0
_SWEEPS = 6

Family = tuple[tuple[str, ...], tuple[str, ...]]
"""(parents, children eldest first); no parents for siblings whose parents aren't in the tree."""


@dataclass(frozen=True)
class Household:
    """What placement reads: each person's row, the couples, and the families."""

    generation: Mapping[str, int]
    partners: tuple[tuple[str, str], ...]
    families: tuple[Family, ...]


def place(household: Household, components: Sequence[Sequence[str]]) -> dict[str, float]:
    """Each person's place along their row. Components sit left to right, in the order given."""
    x: dict[str, float] = {}
    left = 0.0
    for members in components:
        placed = _Placement(household, members).run()
        shift = left - min(placed.values())
        x.update({person: at + shift for person, at in placed.items()})
        left = max(x.values()) + COMPONENT_GAP
    return x


class _Placement:
    """One connected household, placed by sweeps."""

    def __init__(self, household: Household, members: Sequence[str]) -> None:
        inside = set(members)
        self._families = [f for f in household.families if inside.intersection(f[1])]
        self._rows = _blocks(members, household.generation, household.partners)
        self._partners = {
            person: [other for other in block if other != person]
            for blocks in self._rows.values()
            for block in blocks
            for person in block
        }
        self._child_of = {child: f for f in self._families for child in f[1]}
        self._parent_of: dict[str, list[Family]] = {}
        for family in self._families:
            for parent in family[0]:
                self._parent_of.setdefault(parent, []).append(family)
        self.x: dict[str, float] = {}
        for blocks in self._rows.values():
            self._assign(blocks, _pack([0.0] * len(blocks), blocks, [1.0] * len(blocks)))

    def run(self) -> dict[str, float]:
        rows = sorted(self._rows)
        for _ in range(_SWEEPS):
            for row in rows[1:]:
                self._settle(row, self._under_parents)
            for row in reversed(rows[:-1]):
                self._settle(row, self._over_children)
        for row in rows[1:]:
            self._settle(row, self._under_parents)
        return self.x

    def _settle(self, row: int, wish: Callable[[str], float | None]) -> None:
        blocks = self._rows[row]
        wishes = {person: wish(person) for block in blocks for person in block}
        where = {person: self.x[person] if w is None else w for person, w in wishes.items()}
        for block in blocks:
            # Stable: partners who want the same place keep the order they had.
            block.sort(key=where.__getitem__)
        desired = [self._desired(block, wishes) for block in blocks]
        lefts = [left for left, _ in desired]
        weights = [weight for _, weight in desired]
        order = sorted(
            range(len(blocks)),
            key=lambda i: (lefts[i] + _span(blocks[i]) / 2, self.x[blocks[i][0]]),
        )
        blocks[:] = [blocks[i] for i in order]
        self._assign(blocks, _pack([lefts[i] for i in order], blocks, [weights[i] for i in order]))

    def _desired(self, block: list[str], wishes: Mapping[str, float | None]) -> tuple[float, float]:
        """Where the block's left end wants to be, and how hard: one per member who asked.

        A block nobody in it asked a place for stays put, and gives way to the ones that did.
        """
        asked = [
            wanted - index * PARTNER_STEP
            for index, person in enumerate(block)
            if (wanted := wishes[person]) is not None
        ]
        if not asked:
            return self.x[block[0]], 0.5
        return _mean(asked), float(len(asked))

    def _assign(self, blocks: list[list[str]], lefts: list[float]) -> None:
        for block, left in zip(blocks, lefts, strict=True):
            for index, person in enumerate(block):
                self.x[person] = left + index * PARTNER_STEP

    def _under_parents(self, person: str) -> float | None:
        family = self._child_of.get(person)
        if family is None:
            return None
        order = self._facing(family)
        middle = (len(order) - 1) / 2
        return self._knot(family) + (order.index(person) - middle) * BLOCK_GAP

    def _over_children(self, person: str) -> float | None:
        families = self._parent_of.get(person)
        if not families:
            return None
        return _mean([_mean([self.x[c] for c in children]) for _, children in families])

    def _knot(self, family: Family) -> float:
        parents, children = family
        return _mean([self.x[p] for p in parents or children])

    def _facing(self, family: Family) -> list[str]:
        """The children in the order they stand: married ones toward their partner's side."""
        knot = self._knot(family)
        children = family[1]

        def side(child: str) -> int:
            anchors = [self._anchor(partner) for partner in self._partners[child]]
            if not anchors:
                return 0
            pull = _mean(anchors) - knot
            return (pull > 0) - (pull < 0)

        return sorted(children, key=lambda c: (side(c), children.index(c)))

    def _anchor(self, person: str) -> float:
        """Where a partner's own family hangs, or where they stand without one."""
        family = self._child_of.get(person)
        return self.x[person] if family is None or not family[0] else self._knot(family)


def _blocks(
    members: Sequence[str], generation: Mapping[str, int], partners: Sequence[tuple[str, str]]
) -> dict[int, list[list[str]]]:
    """Each row's blocks: people joined by a partner on the same row, in the members' order."""
    inside = set(members)
    root = {person: person for person in members}

    def find(person: str) -> str:
        while root[person] != person:
            person = root[person]
        return person

    for a, b in partners:
        if a in inside and b in inside and generation[a] == generation[b]:
            root[find(b)] = find(a)
    grouped: dict[str, list[str]] = {}
    for person in members:
        grouped.setdefault(find(person), []).append(person)
    rows: dict[int, list[list[str]]] = {}
    for block in grouped.values():
        rows.setdefault(generation[block[0]], []).append(block)
    return rows


def _span(block: Sequence[str]) -> float:
    return (len(block) - 1) * PARTNER_STEP


def _pack(lefts: list[float], blocks: Sequence[Sequence[str]], weights: list[float]) -> list[float]:
    """The lefts closest to `lefts` (weighted least squares) that keep the blocks apart, in order."""
    offsets, at = [], 0.0
    for block in blocks:
        offsets.append(at)
        at += _span(block) + BLOCK_GAP
    pooled = _nondecreasing([left - off for left, off in zip(lefts, offsets, strict=True)], weights)
    return [value + off for value, off in zip(pooled, offsets, strict=True)]


def _nondecreasing(values: list[float], weights: list[float]) -> list[float]:
    """The weighted least-squares nondecreasing fit to `values` (pool adjacent violators)."""
    pools: list[list[float]] = []  # [mean, weight, count]
    for value, weight in zip(values, weights, strict=True):
        pools.append([value, weight, 1])
        while len(pools) > 1 and pools[-2][0] > pools[-1][0]:
            mean_b, weight_b, count_b = pools.pop()
            mean_a, weight_a, count_a = pools.pop()
            total = weight_a + weight_b
            pools.append(
                [(mean_a * weight_a + mean_b * weight_b) / total, total, count_a + count_b]
            )
    return [mean for mean, _, count in pools for _ in range(int(count))]


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)
