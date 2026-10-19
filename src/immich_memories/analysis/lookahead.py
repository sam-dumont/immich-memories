"""Prepare what a one-by-one walk may reach, in a few rounds instead of one per candidate."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any


class Lookahead:
    """Prepare the next candidates of a walk before the walk asks about them.

    Preparing a candidate costs a round of fixed work whatever the round carries, so walking
    candidates one by one pays that round for each. Preparing them all up front would read far
    more than most walks reach. The window doubles instead (1, 1, 2, 4, 8, ...), so a walk that
    stops early reads about what it used and a long one costs a logarithmic number of rounds.
    Which candidate wins never depends on this: preparation only supplies facts earlier.
    """

    def __init__(
        self,
        items: Sequence[Any],
        prepare: Callable[[Sequence[Any]], object] | None,
        row_of: Callable[[Any], Any] = lambda item: item,
    ) -> None:
        self._items = items
        self._prepare = prepare
        self._row_of = row_of
        self._ahead = 0

    def reach(self, position: int) -> None:
        """Make sure the item at ``position`` and a doubling window after it are prepared."""
        if self._prepare is None or position < self._ahead:
            return
        end = min(len(self._items), position + max(1, self._ahead))
        self._prepare([self._row_of(item) for item in self._items[position:end]])
        self._ahead = end
