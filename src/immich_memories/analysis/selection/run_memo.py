"""Per-run memos for facts a run asks for again and again while the cut is decided."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

K = TypeVar("K")
V = TypeVar("V")


def remembered_answers(read: Callable[[K], V | None]) -> Callable[[K], V | None]:
    """``read`` that asks once per key, whenever the answer is there.

    An empty answer is asked again: a preview that was not cached a minute ago may be now, and a
    memo that kept the gap would change which pictures the review can compare.
    """
    answers: dict[K, V] = {}

    def ask(key: K) -> V | None:
        if key in answers:
            return answers[key]
        answer = read(key)
        if answer is not None:
            answers[key] = answer
        return answer

    return ask
