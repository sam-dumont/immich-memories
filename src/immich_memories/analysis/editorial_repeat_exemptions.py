"""What no repetition check takes out of a film, asked once for all of them (#2071).

The final duplicate review (`editorial_final_hash_review`) runs over the finished cut. The
checks that ask the same question before it, while the cut can still be refilled (the capacity
fold, the look-alike check, the depth fill), read the exemptions from here so the two cannot
drift apart.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def repeat_may_be_refused(
    candidate: Mapping[str, Any],
    keeper: Mapping[str, Any],
    *,
    only_shot: bool = False,
    twins_stay: bool = False,
) -> bool:
    """Whether a frame may be taken out of the film as a repeat of `keeper`.

    The one place the final review's exemptions live, so every check that asks the repetition
    question before it (the capacity fold, the look-alike check, the depth fill) honours the
    same ones (#2071). A favourite is never refused for a picture the owner did not star: the
    favourite wins its moment. A close family member's only shot never leaves for its
    look-alike (`only_shot`). The film floor needs no argument: refusing a repeat always
    leaves its keeper in the cut.

    Two starred frames of one scene are the owner's one moment starred twice, and the final
    review folds them by their time apart over the finished cut. A check that runs before any
    carrier is picked cannot see that, so it passes `twins_stay` and leaves the twins to it.
    """
    if candidate.get("favourite") and (twins_stay or not keeper.get("favourite")):
        return False
    return not only_shot
