"""Where each person of the family tree sits along their row (#2797).

Rows are generations, decided before this runs. Partners sit side by side as one block. A
family's children stand together under their parents' knot. When a couple joins two families,
the two families stand side by side with the couple at the seam, each partner on their own
family's side; a partner whose parents aren't in the tree stands on the outside of their
spouse. Placement is a few sweeps down and up the rows: going down, each block asks for the
place under its parents; going up, each block asks for the place over its children. The row
then keeps its blocks apart while moving them as little as it can, which is an isotonic
regression solved by pooling adjacent violators. Same input, same places: nothing here is
random or depends on dict order.

Where families still overlap (cousins who married, several couples between two families), their
lines to the children go on different heights: `bar_lanes`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from itertools import chain

# Partners stand one unit apart; blocks and the children of a family a little further.
PARTNER_STEP = 1.0
BLOCK_GAP = 1.25
COMPONENT_GAP = 2.0
# Two families' lines to their children closer than this along the row read as one line.
BAR_GAP = 0.3
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


def bar_lanes(household: Household, x: Mapping[str, float]) -> tuple[int, ...]:
    """The height each family's line to its children is drawn at, per family; 0 is the lowest.

    The line runs from the knot over the parents to the outermost child. On one row, lines that
    would overlap or touch go on different heights. The narrowest line takes the lowest free
    height, so a wide line passes above the short ones rather than through their children's
    drop lines.
    """
    bars = []
    for index, (parents, children) in enumerate(household.families):
        xs = [x[child] for child in children]
        knot = _mean([x[parent] for parent in parents] if parents else xs)
        left, right = min(knot, *xs), max(knot, *xs)
        row = min(household.generation[child] for child in children)
        bars.append((row, right - left, left, right, index))
    lanes = [0] * len(bars)
    taken: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for row, _, left, right, index in sorted(bars):
        lane = 0
        while any(
            left <= other_right + BAR_GAP and other_left <= right + BAR_GAP
            for other_left, other_right in taken.get((row, lane), [])
        ):
            lane += 1
        taken.setdefault((row, lane), []).append((left, right))
        lanes[index] = lane
    return tuple(lanes)


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
        order = _SiblingOrder(
            blocks=blocks,
            families=[self._families_of(block) for block in blocks],
            centres=[
                left + _span(block) / 2 for block, (left, _) in zip(blocks, desired, strict=True)
            ],
            weights=[weight for _, weight in desired],
            now=[self.x[block[0]] for block in blocks],
        ).order()
        blocks[:] = [blocks[i] for i in order]
        self._face_outward(blocks, where)
        desired = [self._desired(block, wishes) for block in blocks]
        lefts = [left for left, _ in desired]
        self._assign(blocks, _pack(lefts, blocks, [weight for _, weight in desired]))

    def _families_of(self, block: Sequence[str]) -> tuple[Family, ...]:
        """The families the block's members are children of, each once."""
        return tuple(dict.fromkeys(self._child_of[p] for p in block if p in self._child_of))

    def _face_outward(self, blocks: Sequence[list[str]], where: Mapping[str, float]) -> None:
        """Each partner toward their own siblings; a partner with no family in the row outward."""
        stands: dict[Family, list[int]] = {}
        for index, block in enumerate(blocks):
            for family in self._families_of(block):
                stands.setdefault(family, []).append(index)
        for index, block in enumerate(blocks):
            pulls = {person: self._pull(person, index, stands) for person in block}
            outward = -_sign(sum(pulls.values()))
            for person in block:
                if person not in self._child_of:
                    pulls[person] = outward
            block.sort(key=lambda person: (pulls[person], where[person]))

    def _pull(self, person: str, index: int, stands: Mapping[Family, list[int]]) -> int:
        """-1 when the person's siblings stand to the left of block `index`, 1 right, else 0."""
        family = self._child_of.get(person)
        if family is None:
            return 0
        others = [i for i in stands[family] if i != index]
        return _sign(_mean(others) - index) if others else 0

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
            return _sign(pull)

        return sorted(children, key=lambda c: (side(c), children.index(c)))

    def _anchor(self, person: str) -> float:
        """Where a partner's own family hangs, or where they stand without one."""
        family = self._child_of.get(person)
        return self.x[person] if family is None or not family[0] else self._knot(family)


@dataclass(frozen=True)
class _SiblingOrder:
    """The order a row's blocks stand in, so each family's children stand together.

    Families a couple joins (a bridge block holds a child of each) form one run: along a chain
    of such families, each family's own blocks sit between its bridges, so every couple stands
    at the seam of the two families. Within a family, married blocks go to the end away from its
    bridges, so a partner with no family here stands on the outside. Runs, and blocks of no
    family, stand in the order of where they want to be.
    """

    blocks: Sequence[Sequence[str]]
    families: Sequence[tuple[Family, ...]]
    centres: Sequence[float]
    weights: Sequence[float]
    now: Sequence[float]

    def order(self) -> list[int]:
        runs: dict[Family | int, list[int]] = {}
        root = self._joined()
        for index, families in enumerate(self.families):
            runs.setdefault(root[families[0]] if families else index, []).append(index)
        placed = [self._run(indices) for indices in runs.values()]
        placed.sort(key=lambda run: (self._centre(run), min(self.now[i] for i in run)))
        return list(chain.from_iterable(placed))

    def _joined(self) -> dict[Family, Family]:
        """Each family's first family (in sort order) among those couples join it to."""
        root: dict[Family, Family] = {f: f for families in self.families for f in families}

        def find(family: Family) -> Family:
            while root[family] != family:
                family = root[family]
            return family

        for families in self.families:
            for other in families[1:]:
                a, b = sorted((find(families[0]), find(other)))
                root[b] = a
        return {family: find(family) for family in root}

    def _centre(self, indices: Sequence[int]) -> float:
        weights = [self.weights[i] for i in indices]
        return sum(self.centres[i] * w for i, w in zip(indices, weights, strict=True)) / sum(
            weights
        )

    def _run(self, indices: list[int]) -> list[int]:
        rank = self._ranks(indices)
        bridged: dict[Family, list[int]] = {}
        for i in indices:
            for family in self.families[i]:
                bridged.setdefault(family, []).extend(
                    rank[f] for f in self.families[i] if f != family
                )

        def outer(i: int) -> int:
            """-1 for a married block at its family's left end, 1 at its right, else 0."""
            if len(self.families[i]) != 1 or len(self.blocks[i]) == 1:
                return 0
            family = self.families[i][0]
            if bridged[family]:
                return -_sign(_mean(bridged[family]) - rank[family])
            return _sign(self.centres[i] - self._centre(self._stands(family, indices)))

        return sorted(
            indices,
            key=lambda i: (
                _mean([rank[f] for f in self.families[i]]) if self.families[i] else 0.0,
                outer(i),
                self.centres[i],
                self.now[i],
            ),
        )

    def _stands(self, family: Family, indices: Sequence[int]) -> list[int]:
        return [i for i in indices if family in self.families[i]]

    def _ranks(self, indices: Sequence[int]) -> dict[Family, int]:
        """The families of a run, left to right: along their chain when couples chain them."""
        families = sorted({f for i in indices for f in self.families[i]})
        near: dict[Family, set[Family]] = {family: set() for family in families}
        for i in indices:
            for family in self.families[i]:
                near[family].update(f for f in self.families[i] if f != family)
        centre = {f: self._centre(self._stands(f, indices)) for f in families}
        chain = sum(len(n) for n in near.values()) == 2 * (len(families) - 1)
        if not families or not chain or any(len(n) > 2 for n in near.values()):
            ordered = sorted(families, key=lambda f: (centre[f], f))
        else:
            ordered = [min((f for f in families if len(near[f]) < 2), key=lambda f: (centre[f], f))]
            while len(ordered) < len(families):
                ordered.append(min(near[ordered[-1]] - set(ordered)))
        return {family: rank for rank, family in enumerate(ordered)}


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


def _sign(value: float) -> int:
    return (value > 0) - (value < 0)
