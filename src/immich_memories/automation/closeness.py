"""How close a person is to the library's owner, as the people registry records it (#2232)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from immich_memories.people.context import PersonPromptContext
from immich_memories.people.relationships import is_close_family

# The registry's tier says how often someone is in the owner's life. A film about an
# acquaintance's birthday is worth less than one about a child's, however many pictures it has.
_TIER_WEIGHT = {"inner": 1.0, "recurring": 0.6, "episodic": 0.3, "event": 0.15}

# Someone the registry says nothing about is not marked down: a library that never ran the
# people scan scores the way it did before closeness existed.
UNKNOWN_WEIGHT = 1.0


def closeness_weight(context: PersonPromptContext) -> float | None:
    """1.0 for the inner tier or a partner, child or parent; the tier's weight otherwise."""
    if context.role and is_close_family(context.role):
        return 1.0
    return _TIER_WEIGHT.get(context.tier or "")


def is_close(context: PersonPromptContext) -> bool:
    """Whether a monthly film of this person is worth proposing on its own."""
    return closeness_weight(context) == 1.0


def closeness_by_person(contexts: Mapping[str, PersonPromptContext]) -> dict[str, float]:
    """Every known Immich person id to its weight; ids the registry cannot weigh are left out."""
    weights = {pid: closeness_weight(ctx) for pid, ctx in contexts.items()}
    return {pid: weight for pid, weight in weights.items() if weight is not None}


def group_weight(person_ids: Sequence[str], closeness: Mapping[str, float] | None) -> float:
    """The average weight of the people a pair or a group film is about."""
    if not closeness or not person_ids:
        return UNKNOWN_WEIGHT
    return sum(closeness.get(pid, UNKNOWN_WEIGHT) for pid in person_ids) / len(person_ids)
