"""Remember a pure function of an object per object, not per equal-looking copy."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def per_object(compute: Callable[[T], R], *, keep: int = 65536) -> Callable[[T], R]:
    """``compute`` that runs once per live object.

    A changed copy of an asset (``model_copy(update=...)``) is another object and is computed on
    its own, so a copy with a new favourite flag or people never reads its original's answer. The
    memo holds the object itself, which keeps its identity from being reused, and forgets the
    oldest objects past ``keep``.
    """
    seen: OrderedDict[int, tuple[Any, R]] = OrderedDict()

    def remembered(obj: T) -> R:
        entry = seen.get(id(obj))
        if entry is not None and entry[0] is obj:
            seen.move_to_end(id(obj))
            return entry[1]
        result = compute(obj)
        seen[id(obj)] = (obj, result)
        if len(seen) > keep:
            seen.popitem(last=False)
        return result

    return remembered
